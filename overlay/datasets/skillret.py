"""SkillRet 原生 BM25 检索与 trec_eval 评分的资源包适配器。"""

import argparse
import asyncio
from functools import lru_cache
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from datasets.package import read_package_index, resource_path
from evaluation.contracts import AgentResult, PreparedTask, Score, Task, TrialContext
from utils.json_io import write_json


DATASET_ID = "ThakiCloud/SKILLRET"
DATASET_REVISION = "6583d7d2ed07644d0fb8938ed8178f3a7dc42a12"
TASK_FORMAT = "research-skillret-v1"
K_VALUES = (5, 10, 15)


def _jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"需要非空 JSONL 对象列表：{path}")
    return rows


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_tasks(index: Path, task_ids: list[str] | None = None) -> list[Task]:
    package = read_package_index(index, task_format=TASK_FORMAT)
    files = {}
    for name in ("skills", "queries", "qrels"):
        record = package.metadata["resources"][name]
        path = resource_path(package.root, record["path"])
        if _sha256(path) != record["sha256"]:
            raise ValueError(f"SkillRet 原始资源哈希不匹配：{name}")
        files[name] = path
    skills = _jsonl(files["skills"])
    skill_ids = [row["id"] for row in skills]
    if (any(not isinstance(sid, str) or not sid for sid in skill_ids)
            or len(set(skill_ids)) != len(skill_ids)):
        raise ValueError("候选技能 ID 必须唯一且非空")
    queries = {}
    for query in _jsonl(files["queries"]):
        query_id = query["id"]
        if query_id in queries or not isinstance(query.get("query"), str) or not query["query"].strip():
            raise ValueError(f"SkillRet 查询重复或为空：{query_id}")
        queries[query_id] = query
    qrels = {}
    candidates = set(skill_ids)
    for label in _jsonl(files["qrels"]):
        query_id, skill_id, relevance = label["query_id"], label["skill_id"], label["relevance"]
        if query_id not in queries or skill_id not in candidates or type(relevance) is not int or relevance < 0:
            raise ValueError("SkillRet 相关性标签无效或引用不存在的查询/技能")
        labels = qrels.setdefault(query_id, {})
        if skill_id in labels:
            raise ValueError("SkillRet 相关性标签重复")
        labels[skill_id] = relevance
    rows = {row["id"]: row for row in package.index["tasks"]}
    if set(rows) != set(queries):
        raise ValueError("SkillRet 索引与原始查询集合不一致")
    selected = list(rows) if task_ids is None else task_ids
    if not selected or len(set(selected)) != len(selected) or set(selected) - rows.keys():
        raise ValueError("任务选择必须非空、无重复且属于 SkillRet 查询集合")
    tasks = []
    for query_id in selected:
        labels = qrels.get(query_id, {})
        if not any(value > 0 for value in labels.values()):
            raise ValueError(f"SkillRet 查询没有正相关标签：{query_id}")
        tasks.append(Task(
            id=query_id, instruction=queries[query_id]["query"],
            metadata={"qrels": labels},
            source={"index": str(package.index_path), "row": rows[query_id],
                    "dataset_sha256": package.dataset_sha256,
                    "index_sha256": package.index_sha256},
        ))
    return tasks


def prepare_task(task: Task, destination: Path, condition: str) -> PreparedTask:
    if condition != "full-text":
        raise ValueError("SkillRet 原生基线仅支持 full-text 条件")
    package = read_package_index(task.source["index"], task_format=TASK_FORMAT)
    if (package.dataset_sha256 != task.source["dataset_sha256"]
            or package.index_sha256 != task.source["index_sha256"]):
        raise ValueError("实验计划生成后 SkillRet 资源包入口发生变化")
    record = package.metadata["resources"]["skills"]
    destination.mkdir(parents=True)
    # 评分标签仅保存在 Task.metadata，检索执行器只读取查询和完整候选库。
    write_json(destination / "query.json", {
        "id": task.id, "query": task.instruction,
        "corpus": str(resource_path(package.root, record["path"])),
        "corpus_sha256": record["sha256"],
    })
    return PreparedTask(task_dir=destination)


def create_environment(task_dir: Path, *, output_dir: Path, **options):
    from environment.local import LocalEnvironment

    return LocalEnvironment(workdir=task_dir, **options)


@lru_cache(maxsize=1)
def _bm25_index(path: str, sha256: str, modified_ns: int, size: int):
    """进程内复用完整候选索引；文件身份变化时重新校验和构建。"""
    import bm25s

    corpus = Path(path)
    if _sha256(corpus) != sha256:
        raise ValueError("SkillRet 候选库内容与资源包声明不一致")
    skills = _jsonl(corpus)
    texts = []
    for skill in skills:
        name = (skill.get("name") or "").strip()
        description = (skill.get("description") or "").strip()
        body = (skill.get("skill_md") or description).strip()
        texts.append(f"{name} | {description} | {body}")
    retriever = bm25s.BM25()
    retriever.index(bm25s.tokenize(texts, stopwords="en", show_progress=False), show_progress=False)
    return retriever, [skill["id"] for skill in skills]


def _retrieve(query: dict, top_k: int) -> dict:
    import bm25s

    path = Path(query["corpus"])
    stat = path.stat()
    retriever, ids = _bm25_index(str(path), query["corpus_sha256"], stat.st_mtime_ns, stat.st_size)
    tokens = bm25s.tokenize(query["query"], stopwords="en", show_progress=False)
    if len(tokens.vocab) == 0:
        tokens = bm25s.tokenize("NONE", stopwords=[], show_progress=False)
    hits, scores = retriever.retrieve(tokens, corpus=ids, k=min(top_k, len(ids)), show_progress=False)
    results = {str(sid): float(score) for sid, score in zip(hits[0], scores[0]) if score > 0}
    return {"query_id": query["id"], "corpus_sha256": query["corpus_sha256"],
            "candidate_count": len(ids), "top_k": top_k, "scores": results,
            "versions": {name: version(name) for name in ("bm25s", "pytrec-eval-terrier")}}


async def execute(*, instruction: str, model: dict, tools, environment, output_dir: Path,
                  workspace=None, timeout_sec=900, skill_catalog=None, recorder=None, top_k=20) -> AgentResult:
    if model["model"] != "bm25" or tools or recorder is not None or skill_catalog:
        raise ValueError("SkillRet BM25 基线需要 model=bm25、空工具和无 LLM recorder")
    if type(top_k) is not int or top_k < max(K_VALUES):
        raise ValueError("top_k 必须是至少为 15 的整数，覆盖全部评分截断点")
    query = json.loads((environment.workdir / "query.json").read_text(encoding="utf-8"))
    if query["query"] != instruction:
        raise ValueError("检索查询与本次任务指令不一致")
    evidence = await asyncio.wait_for(asyncio.to_thread(_retrieve, query, top_k), timeout=timeout_sec)
    write_json(Path(output_dir) / "retrieval.json", evidence)
    result = AgentResult(final_response=json.dumps(evidence["scores"]), finish_reason="finished")
    write_json(Path(output_dir) / "result.json", {"finish_reason": result.finish_reason, **evidence})
    return result


async def evaluate(context: TrialContext, agent: AgentResult) -> Score:
    import pytrec_eval

    evidence = json.loads((context.output_dir / "agent" / "retrieval.json").read_text(encoding="utf-8"))
    query = json.loads((context.prepared.task_dir / "query.json").read_text(encoding="utf-8"))
    if evidence["query_id"] != context.task.id or evidence["corpus_sha256"] != query["corpus_sha256"]:
        raise ValueError("检索评分证据与本次任务不匹配")
    scores = evidence["scores"]
    if scores != json.loads(agent.final_response) or any(not math.isfinite(value) for value in scores.values()):
        raise ValueError("检索结果分数无效或与执行产物不一致")
    cutoffs = ",".join(map(str, K_VALUES))
    measures = {f"{metric}.{cutoffs}" for metric in ("ndcg_cut", "recall", "map_cut", "P")}
    evaluator = pytrec_eval.RelevanceEvaluator({context.task.id: context.task.metadata["qrels"]}, measures)
    raw = evaluator.evaluate({context.task.id: scores})[context.task.id]
    metrics = {"candidate_count": evidence["candidate_count"]}
    for k in K_VALUES:
        for name, key in (("NDCG", "ndcg_cut"), ("Recall", "recall"), ("MAP", "map_cut"), ("Precision", "P")):
            metrics[f"{name}@{k}"] = raw[f"{key}_{k}"]
        metrics[f"Completeness@{k}"] = float(raw[f"recall_{k}"] == 1.0)
    score = Score(reward=metrics["NDCG@10"], metrics=metrics)
    write_json(context.output_dir / "verifier" / "result.json", {"reward": score.reward, "metrics": metrics})
    return score


def build_package(output: Path, revision: str = DATASET_REVISION) -> None:
    """下载固定 Hub 提交的测试集，原始 JSONL 保持逐字节一致。"""
    import requests

    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("revision 必须为完整的 Hugging Face 提交 SHA")
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"目标资源包已存在：{output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".skillret-", dir=output.parent) as staging:
        root = Path(staging) / "package"
        resources = {}
        for name in ("skills", "queries", "qrels"):
            relative = f"{name}/test.jsonl"
            path = root / relative
            path.parent.mkdir(parents=True)
            url = f"https://huggingface.co/datasets/{DATASET_ID}/resolve/{revision}/data/{relative}?download=true"
            with requests.get(url, stream=True, timeout=(20, 120)) as response:
                response.raise_for_status()
                with path.open("wb") as stream:
                    for chunk in response.iter_content(1024 * 1024):
                        stream.write(chunk)
            resources[name] = {"path": relative, "sha256": _sha256(path)}
        tasks = [{"id": query["id"]} for query in _jsonl(root / "queries/test.jsonl")]
        write_json(root / "index.json", {"schema_version": 1, "task_count": len(tasks), "tasks": tasks})
        write_json(root / "dataset.json", {
            "schema_version": 1, "id": "skillret", "version": revision,
            "task_format": TASK_FORMAT, "license": "Apache-2.0",
            "provenance": {"dataset": f"https://huggingface.co/datasets/{DATASET_ID}", "revision": revision, "split": "test"},
            "resources": resources,
        })
        load_tasks(root / "index.json")
        root.rename(output)
    print(f"SkillRet 资源包：{output}（{len(tasks)} 条查询）")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/skillret"))
    parser.add_argument("--revision", default=DATASET_REVISION)
    args = parser.parse_args()
    build_package(args.output, args.revision)
