"""OfficeQA Pro 资源包适配器：加载、准备、隔离检查和官方评分。

题面与作答格式对两个 harness 完全共用：instruction 只包含 question 和通用作答格式，
source_files、source_docs 与 ground truth 只保存在任务元数据和评估侧文件中。
"""

import argparse
import hashlib
import importlib.util
import json
import os
from functools import lru_cache
from pathlib import Path
import shutil
import sys

from datasets.package import read_package_index, resource_path
from evaluation.contracts import PreparedTask, Score, Task, TrialContext
from utils.json_io import write_json


DATASET_ID = "databricks/officeqa"
DATASET_REVISION = "763a8366abf2a3605c381d53586d844dc60fa756"
TASK_FORMAT = "research-officeqa-v1"
CONDITION = "full-corpus-txt"
EXPECTED_QUESTIONS = 133
EXPECTED_CORPUS_FILES = 697
TASK_TIMEOUT_SEC = 300
ANSWER_FORMAT = (
    "Answer format (shared by every harness):\n"
    "- Work only from the TXT corpus provided in your task environment; do not use outside "
    "knowledge, web search, or the official answer key.\n"
    "- The total budget for this question is 300 seconds. Search narrowly, keep tool output "
    "small, and stop in time to submit the final answer.\n"
    "- Put only the concise final answer inside <FINAL_ANSWER>...</FINAL_ANSWER> on a single "
    "line. Keep citations and calculation steps outside the tag.\n"
    "- Use the unit, sign and rounding that the question asks for. If the exact figure cannot "
    "be located in time, submit your best supported value before the budget ends."
)
DEFAULT_REWARD_PATH = Path(__file__).resolve().parents[2] / "officeqa" / "reward.py"


def _instruction(question: str) -> str:
    return f"{question.strip()}\n\n{ANSWER_FORMAT}"


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _split_sources(value: str) -> list[str]:
    return [part.strip() for part in value.splitlines() if part.strip()]


def _read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"需要非空 JSONL 对象列表：{path}")
    return rows


def load_tasks(index: Path, task_ids: list[str] | None = None) -> list[Task]:
    package = read_package_index(index, task_format=TASK_FORMAT)
    root = package.root
    resources = package.metadata.get("resources") or {}
    try:
        answers_record = resources["answers"]
        manifest_record = resources["corpus_manifest"]
    except KeyError as exc:
        raise ValueError("dataset.json 缺少 answers 或 corpus_manifest 资源") from exc
    answers_path = resource_path(root, answers_record["path"])
    manifest_path = resource_path(root, manifest_record["path"])
    if _sha256(answers_path) != answers_record["sha256"]:
        raise ValueError("OfficeQA answers.jsonl 哈希与 dataset.json 不一致")
    if _sha256(manifest_path) != manifest_record["sha256"]:
        raise ValueError("OfficeQA corpus-manifest.json 哈希与 dataset.json 不一致")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    corpus = resource_path(root, resources["corpus"]["path"])
    _verify_corpus(corpus, manifest)

    answers = {row["uid"]: row for row in _read_jsonl(answers_path)}
    rows = {row["id"]: row for row in package.index["tasks"]}
    selected = list(rows) if task_ids is None else task_ids
    if not selected or len(set(selected)) != len(selected) or set(selected) - rows.keys():
        raise ValueError("任务选择必须非空、无重复且属于 OfficeQA Pro 索引")
    tasks = []
    for uid in selected:
        row = rows[uid]
        question = json.loads(
            resource_path(root, row["question_file"]).read_text(encoding="utf-8")
        )
        if question.get("uid") != uid or not isinstance(question.get("question"), str):
            raise ValueError(f"OfficeQA 题面与索引不一致：{uid}")
        answer = answers.get(uid)
        if answer is None or not str(answer.get("answer", "")).strip():
            raise ValueError(f"OfficeQA 缺少参考答案：{uid}")
        tasks.append(Task(
            id=uid,
            instruction=_instruction(question["question"]),
            metadata={
                "answer": answer["answer"],
                "source_files": list(answer.get("source_files") or []),
                "source_docs": list(answer.get("source_docs") or []),
                "difficulty": answer.get("difficulty"),
            },
            source={
                "index": str(package.index_path), "row": row,
                "dataset_sha256": package.dataset_sha256,
                "index_sha256": package.index_sha256,
                "question_sha256": _sha256(resource_path(root, row["question_file"])),
            },
            agent_timeout_sec=TASK_TIMEOUT_SEC,
        ))
    return tasks


def _verify_corpus(corpus: Path, manifest: dict) -> None:
    root = Path(corpus)
    files = manifest.get("files") or {}
    if len(files) != manifest.get("count") or len(files) != EXPECTED_CORPUS_FILES:
        raise ValueError("OfficeQA 语料清单数量与预期不一致")
    total = 0
    for name, digest in files.items():
        path = root / name
        if not path.is_file():
            raise ValueError(f"OfficeQA 语料缺少文件：{name}")
        if _sha256(path) != digest:
            raise ValueError(f"OfficeQA 语料文件哈希不匹配：{name}")
        total += path.stat().st_size
    if total != manifest.get("bytes"):
        raise ValueError("OfficeQA 语料总字节数与清单不一致")


def prepare_task(task: Task, destination: Path, condition: str) -> PreparedTask:
    if condition != CONDITION:
        raise ValueError(f"OfficeQA 仅支持 {CONDITION} 条件")
    package = read_package_index(task.source["index"], task_format=TASK_FORMAT)
    if (package.dataset_sha256 != task.source["dataset_sha256"]
            or package.index_sha256 != task.source["index_sha256"]):
        raise ValueError("实验计划生成后 OfficeQA 资源包入口发生变化")
    resources = package.metadata["resources"]
    corpus = resource_path(package.root, resources["corpus"]["path"])
    manifest = json.loads(
        resource_path(package.root, resources["corpus_manifest"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    # 环境工厂读取后立即删除这个文件，答题 agent 的工作目录中不会留下宿主路径。
    destination.mkdir(parents=True)
    write_json(destination / ".officeqa-sandbox.json", {
        "task_id": task.id,
        "corpus_dir": str(corpus),
        "corpus_count": manifest["count"],
        "corpus_bytes": manifest["bytes"],
        "dataset_revision": package.metadata["version"],
        "condition": condition,
    })
    return PreparedTask(task_dir=destination)


@lru_cache(maxsize=1)
def _sandbox_checks() -> dict:
    return {
        "corpus": "find /workspace/corpus -maxdepth 1 -name '*.txt' | wc -l",
        "root_entries": "ls / | tr '\\n' ' '",
        "host_paths": "(ls /mnt/d >/dev/null 2>&1 || ls /mnt/c >/dev/null 2>&1) && echo present || echo absent",
        "corpus_writable": "touch /workspace/corpus/.officeqa-probe 2>/dev/null && echo writable || echo readonly",
        "workspace_writable": "touch /workspace/.officeqa-probe && echo writable || echo readonly",
        "api_key": "printf %s \"${DEEPSEEK_API_KEY:-absent}\"",
        "network": "python3 -c \"import socket; socket.setdefaulttimeout(2); "
                   "socket.create_connection(('1.1.1.1', 443))\" >/dev/null 2>&1 "
                   "&& echo reachable || echo blocked",
        "user": "id -un",
        "image": "python3 -V",
    }


async def setup_environment(context: TrialContext) -> None:
    script = "\n".join(
        [f"printf '%s=' {name}; {command}; echo"
         for name, command in _sandbox_checks().items()]
        + ["rm -f /workspace/.officeqa-probe"]
    )
    result = await context.environment.execute(["bash", "-c", script], timeout=120)
    if not result.success:
        raise RuntimeError(f"OfficeQA 隔离检查命令失败：{result.stderr or result.stdout}")
    checks = {}
    for line in result.stdout.splitlines():
        name, separator, value = line.partition("=")
        if separator:
            checks[name] = value.strip()
    expected = {
        "corpus": str(EXPECTED_CORPUS_FILES), "corpus_writable": "readonly",
        "workspace_writable": "writable", "host_paths": "absent",
        "api_key": "absent", "network": "blocked",
    }
    failures = {key: checks.get(key) for key, value in expected.items() if checks.get(key) != value}
    if failures:
        raise RuntimeError(f"OfficeQA 隔离检查未通过：{failures}")
    write_json(context.output_dir / "isolation.json", {
        "condition": context.condition,
        "environment_id": getattr(context.environment, "run_id", None),
        "workspace": str(context.prepared.task_dir),
        "checks": checks,
        "tools": ["terminal", "read_file"],
        "instruction_sha256": hashlib.sha256(
            context.task.instruction.encode("utf-8")
        ).hexdigest(),
    })


@lru_cache(maxsize=1)
def _reward_module(path: str, modified_ns: int) -> tuple[object, str]:
    schema = importlib.util.spec_from_file_location("_officeqa_official_reward", path)
    if schema is None or schema.loader is None:
        raise RuntimeError(f"无法加载官方 reward.py：{path}")
    module = importlib.util.module_from_spec(schema)
    # 不在官方仓库里留下 __pycache__：只读取源码执行。
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        schema.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module, _sha256(Path(path))


def _official_reward(path: str | None = None) -> tuple[object, Path, str]:
    reward_path = Path(path or os.environ.get("OFFICEQA_REWARD_PATH")
                       or DEFAULT_REWARD_PATH).resolve(strict=True)
    module, digest = _reward_module(str(reward_path), reward_path.stat().st_mtime_ns)
    return module, reward_path, digest


async def evaluate(context: TrialContext, agent) -> Score:
    raw = agent.final_response or ""
    reward, reward_path, digest = _official_reward()
    ground_truth = context.task.metadata["answer"]
    try:
        extracted = reward.extract_final_answer(raw)
    except Exception as exc:  # 官方解析失败时记为无评分，而不是模型答错
        raise RuntimeError(f"官方 reward.py 无法解析模型输出：{exc}") from exc
    score = reward.score_answer(ground_truth, raw, tolerance=0.0)
    if score not in (0.0, 1.0):
        raise RuntimeError(f"官方 score_answer 返回了非 0/1 值：{score}")
    direct_ok, direct_reason = reward._is_direct_answer_only(ground_truth, extracted)
    try:
        matched, rationale = reward.fuzzy_match_answer(ground_truth, extracted, 0.0)
    except Exception as exc:
        matched, rationale = False, f"fuzzy_match_answer 异常：{exc}"
    metrics = {
        "reward": score,
        "official_score": score,
        "tolerance": 0.0,
        "ground_truth": ground_truth,
        "final_answer": extracted,
        "final_answer_chars": len(extracted),
        "direct_answer_only": bool(direct_ok),
        "direct_answer_reason": direct_reason,
        "match_rationale": rationale,
        "fuzzy_matched": bool(matched),
        "reward_path": str(reward_path),
        "reward_sha256": digest,
        "source_files": context.task.metadata.get("source_files", []),
        "source_docs": context.task.metadata.get("source_docs", []),
        "difficulty": context.task.metadata.get("difficulty"),
        "condition": context.condition,
    }
    # 原始输出与官方评分证据一起保存，便于逐题复核。
    (context.output_dir / "verifier").mkdir(parents=True, exist_ok=True)
    (context.output_dir / "verifier" / "raw-response.txt").write_text(raw, encoding="utf-8")
    write_json(context.output_dir / "verifier" / "result.json", metrics)
    return Score(reward=float(score), metrics=metrics)


def build_package(raw_dir: Path, output: Path) -> None:
    """从固定 revision 的原始下载目录生成最小资源包（题目、答案、语料）。"""
    import csv

    raw_dir = raw_dir.resolve(strict=True)
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"目标资源包已存在：{output}")
    question_file = raw_dir / "officeqa_pro.csv"
    corpus = raw_dir / "treasury_bulletins_parsed" / "transformed"
    with question_file.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"uid", "question", "answer", "source_docs", "source_files", "difficulty"}
        if not required <= set(reader.fieldnames or []):
            raise ValueError(f"officeqa_pro.csv 字段不完整：{reader.fieldnames}")
        rows = list(reader)
    if len(rows) != EXPECTED_QUESTIONS:
        raise ValueError(f"officeqa_pro.csv 应有 {EXPECTED_QUESTIONS} 行，实际 {len(rows)}")
    uids = [row["uid"] for row in rows]
    if len(set(uids)) != len(uids) or any(not uid.strip() for uid in uids):
        raise ValueError("officeqa_pro.csv 的 uid 必须唯一且非空")
    rows.sort(key=lambda row: row["uid"])
    texts = sorted(corpus.glob("*.txt"))
    if len(texts) != EXPECTED_CORPUS_FILES:
        raise ValueError(f"语料应有 {EXPECTED_CORPUS_FILES} 个 TXT，实际 {len(texts)}")

    staging = output.with_name(output.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    (staging / "tasks").mkdir(parents=True)
    manifest = {"schema_version": 1, "count": len(texts), "bytes": 0, "files": {}}
    (staging / "corpus").mkdir()
    for source in texts:
        target = staging / "corpus" / source.name
        shutil.copy2(source, target)
        digest = _sha256(target)
        manifest["files"][source.name] = digest
        manifest["bytes"] += target.stat().st_size

    referenced = set()
    for row in rows:
        uid = row["uid"]
        question = {"uid": uid, "question": row["question"].strip()}
        if not question["question"]:
            raise ValueError(f"题目为空：{uid}")
        write_json(staging / "tasks" / f"{uid}.json", question)
        files = _split_sources(row["source_files"])
        docs = _split_sources(row["source_docs"])
        if not files or not docs:
            raise ValueError(f"题目缺少来源信息：{uid}")
        referenced.update(files)

    missing = sorted(referenced - manifest["files"].keys())
    if missing:
        raise ValueError(f"题目引用的语料文件不存在：{missing[:5]}")
    with (staging / "answers.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps({
                "uid": row["uid"],
                "answer": row["answer"].strip(),
                "source_files": _split_sources(row["source_files"]),
                "source_docs": _split_sources(row["source_docs"]),
                "difficulty": row["difficulty"].strip(),
            }, ensure_ascii=False) + "\n")
    write_json(staging / "corpus-manifest.json", manifest)
    index = {
        "schema_version": 1, "task_count": len(rows),
        "tasks": [{
            "id": row["uid"], "question_file": f"tasks/{row['uid']}.json",
            "source_files": _split_sources(row["source_files"]),
            "source_docs": _split_sources(row["source_docs"]),
            "difficulty": row["difficulty"].strip(),
        } for row in rows],
    }
    write_json(staging / "index.json", index)
    write_json(staging / "dataset.json", {
        "schema_version": 1, "id": "officeqa-pro", "version": DATASET_REVISION,
        "task_format": TASK_FORMAT, "license": "CC-BY-SA-4.0",
        "provenance": {
            "dataset": f"https://huggingface.co/datasets/{DATASET_ID}",
            "revision": DATASET_REVISION, "split": "officeqa_pro",
            "corpus": "treasury_bulletins_parsed/transformed",
            "official_code": "https://github.com/databricks/officeqa",
            "official_commit": "7b9a3c154ef9fb40215bb67934afc43e6799de16",
        },
        "resources": {
            "answers": {"path": "answers.jsonl", "sha256": _sha256(staging / "answers.jsonl")},
            "corpus_manifest": {
                "path": "corpus-manifest.json",
                "sha256": _sha256(staging / "corpus-manifest.json"),
            },
            "corpus": {"path": "corpus", "count": len(texts), "bytes": manifest["bytes"]},
        },
    })
    load_tasks(staging / "index.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging.rename(output)
    print(f"OfficeQA 资源包：{output}")
    print(f"  题目 {len(rows)}；语料 {len(texts)} 个 TXT，{manifest['bytes']} 字节；"
          f"被题目引用的语料 {len(referenced)} 个")
    print(f"  前三条 UID：{[row['uid'] for row in rows[:3]]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path,
                        default=Path(os.environ.get("OFFICEQA_RAW_DIR",
                                                   r"data/officeqa-raw")))
    parser.add_argument("--output", type=Path, default=Path("data/officeqa"))
    arguments = parser.parse_args()
    build_package(arguments.raw, arguments.output)
