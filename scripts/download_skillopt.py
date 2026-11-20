"""Fetch the public SkillOpt checkpoint and verify its recorded hash."""

from hashlib import sha256
import json
from pathlib import Path
from urllib.request import urlopen


def main() -> None:
    target = Path(__file__).resolve().parents[1] / "skillopt"
    metadata = json.loads((target / "source.json").read_text(encoding="utf-8"))
    url = (
        "https://raw.githubusercontent.com/microsoft/SkillOpt/"
        + metadata["revision"] + "/ckpt/officeqa/gpt5.5_skill.md"
    )
    with urlopen(url, timeout=30) as response:
        content = response.read(100_001)
    if len(content) > 100_000 or sha256(content).hexdigest() != metadata["sha256"]:
        raise SystemExit("SkillOpt download does not match the recorded hash.")
    (target / "gpt5.5_skill.md").write_bytes(content)
    print("Verified SkillOpt OfficeQA checkpoint.")


if __name__ == "__main__":
    main()
