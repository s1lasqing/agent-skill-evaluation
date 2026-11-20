"""隔离的 Docker 任务环境：只暴露只读语料与每题独立工作目录。

每次 trial 启动一个无网络、只读根文件系统、丢弃全部 capability 的容器，
仅把语料以只读方式挂载到 /workspace/corpus，把 trial 目录挂载到 /workspace。
宿主项目、题目 CSV、参考答案、评分代码和模型密钥都不会进入容器。
"""

import asyncio
from collections import namedtuple
import math
from pathlib import Path
import subprocess
import time
from uuid import uuid4

from .base import CommandResult, EnvironmentError


_DockerOutput = namedtuple("_DockerOutput", "returncode stdout stderr")


class _ResourceShim:
    """工具桥接接口只读取 registry；本环境不提供注册中心工具。"""

    registry = None


def _docker(args: list[str], *, timeout: float, input_text: str | None = None):
    # 以二进制传递 stdin，避免 Windows 文本模式把 \n 改写成 \r\n，
    # 使容器内的 bash 脚本每行末尾带上 \r。
    completed = subprocess.run(
        ["docker", *args],
        input=None if input_text is None else input_text.encode("utf-8"),
        capture_output=True,
        timeout=timeout,
    )
    return _DockerOutput(
        completed.returncode,
        completed.stdout.decode("utf-8", errors="replace"),
        completed.stderr.decode("utf-8", errors="replace"),
    )


def _windows_mount(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


class DockerSandboxEnvironment:
    def __init__(self, *, workspace_dir: Path, corpus_dir: Path, output_dir: Path | None = None,
                 image: str = "python:3.12-slim", container_prefix: str = "research-officeqa",
                 corpus_mount: str = "/workspace/corpus", workspace_mount: str = "/workspace",
                 memory: str = "1g", pids_limit: int = 256, default_timeout: float = 300,
                 startup_timeout: float = 180, cleanup_timeout: float = 60):
        self.workspace_dir = Path(workspace_dir).resolve()
        self.corpus_dir = Path(corpus_dir).resolve(strict=True)
        self.output_dir = Path(output_dir) if output_dir is not None else None
        self.image = image
        self.corpus_mount = corpus_mount
        self.workspace_mount = workspace_mount
        self.memory = memory
        self.pids_limit = pids_limit
        self.default_timeout = default_timeout
        self.startup_timeout = startup_timeout
        self.cleanup_timeout = cleanup_timeout
        self.name = f"{container_prefix}-{uuid4().hex[:12]}"
        self.run_id = self.name
        self.state = "new"
        self.workdir = workspace_mount
        self.worker_python_executable = "python3"
        self.executor = _ResourceShim()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ 生命周期
    async def start(self) -> None:
        async with self._lock:
            if self.state == "running":
                return
            if self.state != "new":
                raise EnvironmentError("Docker 环境销毁后请重新创建")
            if not self.corpus_dir.is_dir():
                raise EnvironmentError(f"OfficeQA 语料目录不存在：{self.corpus_dir}")
            self.workspace_dir.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(self._start_container)
            self.state = "running"
        # 不持锁等待就绪：execute() 需要获取同一把锁。
        try:
            await self.wait_ready(self.startup_timeout)
        except BaseException:
            await self.destroy()
            raise

    def _start_container(self) -> None:
        args = [
            "run", "-d", "--rm", "--name", self.name,
            "--network", "none", "--read-only", "--tmpfs", "/tmp:rw,size=256m",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", str(self.pids_limit), "--memory", self.memory,
            "--mount", f"type=bind,source={_windows_mount(self.corpus_dir)},"
                       f"target={self.corpus_mount},readonly",
            "--mount", f"type=bind,source={_windows_mount(self.workspace_dir)},"
                       f"target={self.workspace_mount}",
            "--workdir", self.workspace_mount,
            "--env", "HOME=/workspace", "--env", "LANG=C.UTF-8", "--env", "LC_ALL=C.UTF-8",
            self.image, "sleep", "infinity",
        ]
        result = _docker(args, timeout=min(self.startup_timeout, 120))
        if result.returncode != 0:
            raise EnvironmentError(
                f"无法启动 OfficeQA 容器：{result.stderr.strip() or result.stdout.strip()}"
            )

    async def wait_ready(self, timeout: float = 30) -> None:
        deadline = time.monotonic() + timeout
        while True:
            probe = await self.execute(["bash", "-c", "true"], timeout=10)
            if probe.success:
                return
            if time.monotonic() >= deadline:
                raise EnvironmentError(
                    f"OfficeQA 容器在 {timeout:g} 秒内未就绪：{probe.stderr.strip()}"
                )
            await asyncio.sleep(1)

    async def destroy(self) -> None:
        async with self._lock:
            if self.state == "destroyed":
                return
            await asyncio.to_thread(self._stop_container)
            self.state = "destroyed"

    def _stop_container(self) -> None:
        stop = _docker(["stop", "--time", "3", self.name], timeout=self.cleanup_timeout)
        inspect = _docker(["inspect", "--format", "{{.State.Status}}", self.name],
                          timeout=self.cleanup_timeout)
        if inspect.returncode == 0:
            raise EnvironmentError(
                f"OfficeQA 容器清理失败：{self.name} 仍为 {inspect.stdout.strip()}；"
                f"stop 输出 {stop.stderr.strip()}"
            )

    # ------------------------------------------------------------------ 命令与文件
    async def execute(self, argv, *, cwd: str | None = None, timeout: float = 60,
                      service: str = "main") -> CommandResult:
        if service != "main":
            raise ValueError("DockerSandboxEnvironment 仅提供 main 服务")
        if not isinstance(argv, (list, tuple)) or not argv:
            raise ValueError("argv 必须为非空命令序列")
        parts = [str(part) for part in argv]
        command = parts[2] if len(parts) == 3 and parts[:2] == ["bash", "-c"] else " ".join(parts)
        if cwd is None:
            cwd = self.workspace_mount
        cwd = str(cwd)
        if not cwd.startswith("/") or ".." in Path(cwd).parts:
            raise ValueError(f"容器工作目录必须为绝对路径：{cwd!r}")
        seconds = max(1, int(math.ceil(float(timeout))))
        async with self._lock:
            if self.state != "running":
                raise EnvironmentError(f"Docker 环境未运行：{self.state}")
            return await asyncio.to_thread(self._exec_container, command, cwd, seconds)

    def _exec_container(self, command: str, cwd: str, seconds: int) -> CommandResult:
        script = f"/tmp/oq-command-{uuid4().hex}.sh"
        wrapper = f"cat > {script} && timeout -k 5 {seconds} bash -l {script}"
        try:
            result = _docker(
                ["exec", "-i", "--workdir", cwd, "--env", "HOME=/workspace",
                 "--env", "LANG=C.UTF-8", "--env", "LC_ALL=C.UTF-8",
                 self.name, "bash", "-c", wrapper],
                timeout=seconds + 30, input_text=command,
            )
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout if isinstance(exc.stdout, bytes) else (exc.stdout or "").encode()
            error = exc.stderr if isinstance(exc.stderr, bytes) else (exc.stderr or "").encode()
            return CommandResult(
                None, output.decode("utf-8", errors="replace"),
                error.decode("utf-8", errors="replace"), timed_out=True,
            )
        return CommandResult(result.returncode, result.stdout, result.stderr)

    async def upload(self, source, destination: str) -> None:
        source = Path(source).resolve(strict=True)
        parent = str(Path(destination).parent).replace("\\", "/")
        async with self._lock:
            if self.state != "running":
                raise EnvironmentError(f"Docker 环境未运行：{self.state}")
            prepared = _docker(["exec", self.name, "mkdir", "-p", parent], timeout=60)
            if prepared.returncode != 0:
                raise EnvironmentError(f"无法创建容器目录：{prepared.stderr.strip()}")
            if source.is_dir():
                raise ValueError("当前只支持上传单个文件")
            result = _docker(["cp", str(source), f"{self.name}:{destination}"], timeout=120)
            if result.returncode != 0:
                raise EnvironmentError(f"docker cp 上传失败：{result.stderr.strip()}")

    async def download(self, source: str, destination, *, directory: bool = False) -> None:
        destination = Path(destination).resolve()
        async with self._lock:
            if self.state != "running":
                raise EnvironmentError(f"Docker 环境未运行：{self.state}")
            result = _docker(["cp", f"{self.name}:{source}", str(destination)], timeout=120)
            if result.returncode != 0:
                raise EnvironmentError(f"docker cp 下载失败：{result.stderr.strip()}")

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *exc):
        await self.destroy()
