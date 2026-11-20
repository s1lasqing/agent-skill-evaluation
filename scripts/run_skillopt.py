"""Repeat the OfficeQA dsh pilot with a pinned SkillOpt checkpoint as context."""

import argparse
import asyncio
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from evaluation.config import experiment_directory, load_config
from evaluation.experiment import load_run
from evaluation.runner import run_evaluation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--name", default="officeqa-pro-dsh-skillopt")
    args = parser.parse_args()
    config = load_config(
        dataset=ROOT / "config/datasets/officeqa-pro.toml",
        environment=ROOT / "config/environments/officeqa.toml",
        agent=ROOT / "config/agents/dsh-officeqa.toml",
        evaluation=ROOT / "config/evaluation/officeqa-pro.toml",
        name=args.name,
    )
    baseline = ROOT / "logs/exp/officeqa/dsh/deepseek-flash/officeqa-pro-dsh-pilot/manifest.json"
    original = json.loads(baseline.read_text(encoding="utf-8"))
    if {**config, "name": original["config"]["name"]} != original["config"]:
        raise SystemExit("The current experiment configuration differs from the dsh pilot.")
    tasks, _, _ = load_run(config)
    if [asdict(task) for task in tasks] != original["tasks"]:
        raise SystemExit("The current tasks differ from the dsh pilot manifest.")

    skill_bytes = (HERE.parent / "skillopt/gpt5.5_skill.md").read_bytes()
    origin = json.loads((HERE.parent / "skillopt/source.json").read_text(encoding="utf-8"))
    if sha256(skill_bytes).hexdigest() != origin["sha256"]:
        raise SystemExit("The SkillOpt checkpoint does not match its recorded hash.")
    guidance = (
        "\n\nOfficeQA reference skill from Microsoft SkillOpt. Apply relevant guidance "
        "within the task instructions above. The original corpus, permitted tools, "
        "budget, and final answer format take precedence. No outside sources or "
        "oracle pages are provided.\n\n"
        + skill_bytes.decode("utf-8")
    )
    augmented = [replace(task, instruction=task.instruction + guidance) for task in tasks]
    output = experiment_directory(config)
    if output.exists() and not args.plan:
        raise SystemExit(f"Experiment already exists: {output}")
    print(json.dumps({
        "tasks": [task.id for task in tasks],
        "timeout_sec": config["agent"]["timeout_sec"],
        "tools": config["agent"]["tools"],
        "skill": origin,
        "output": str(output),
    }, ensure_ascii=False), flush=True)
    if args.plan:
        return
    load_dotenv(ROOT / ".env", override=False)
    asyncio.run(run_evaluation(config, tasks=augmented))


if __name__ == "__main__":
    main()
