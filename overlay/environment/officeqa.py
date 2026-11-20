"""OfficeQA 环境工厂：读取 prepare 写入的语料位置，创建隔离 Docker 沙箱。"""

import json
from pathlib import Path

from environment.docker_sandbox import DockerSandboxEnvironment


_ALLOWED = {"image", "memory", "pids_limit", "default_timeout", "startup_timeout",
            "cleanup_timeout", "container_prefix", "corpus_mount", "workspace_mount"}


def create_environment(task_dir: Path, *, output_dir: Path, **options):
    unknown = set(options) - _ALLOWED
    if unknown:
        raise ValueError(f"未知的 OfficeQA 环境配置项：{sorted(unknown)}")
    task_dir = Path(task_dir)
    marker = task_dir / ".officeqa-sandbox.json"
    if not marker.is_file():
        raise FileNotFoundError(f"缺少 OfficeQA 沙箱描述文件：{marker}")
    info = json.loads(marker.read_text(encoding="utf-8"))
    # 宿主路径只给环境使用；启动容器前删除，工作目录中不会出现语料或包路径。
    marker.unlink()
    if info.get("condition") != "full-corpus-txt":
        raise ValueError(f"OfficeQA 沙箱条件不匹配：{info.get('condition')}")
    return DockerSandboxEnvironment(
        workspace_dir=task_dir,
        corpus_dir=Path(info["corpus_dir"]),
        output_dir=Path(output_dir),
        **options,
    )
