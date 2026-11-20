"""Apply the experiment extensions to a clean checkout of the pinned framework."""

import argparse
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
REVISION = "6c6131b10b4ec4e108dbaf0e4e53b96f199c0608"


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("research", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    repo = args.research.resolve(strict=True)
    if git(repo, "rev-parse", "HEAD") != REVISION:
        raise SystemExit(f"Expected research checkout {REVISION}")
    if git(repo, "status", "--porcelain"):
        raise SystemExit("Use a clean research checkout.")
    overlay = ROOT / "overlay"
    files = sorted(p.relative_to(overlay) for p in overlay.rglob("*") if p.is_file())
    conflicts = [str(p) for p in files if (repo / p).exists()]
    if conflicts:
        raise SystemExit("Overlay would overwrite: " + ", ".join(conflicts))
    patch = str(ROOT / "patches/research-compat.patch")
    git(repo, "apply", "--check", patch)
    if args.check:
        print(f"Compatible checkout; {len(files)} overlay files.")
        return
    git(repo, "apply", patch)
    for path in files:
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(overlay / path, target)
    print(f"Applied compatibility patch and {len(files)} overlay files to {repo}.")


if __name__ == "__main__":
    main()
