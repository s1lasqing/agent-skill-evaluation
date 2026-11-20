"""Download the pinned OfficeQA Pro/Full data and verify the local files."""

import csv
from pathlib import Path

from huggingface_hub import get_token, snapshot_download
from huggingface_hub.errors import GatedRepoError, HfHubHTTPError


REPO_ID = "databricks/officeqa"
REVISION = "763a8366abf2a3605c381d53586d844dc60fa756"
RAW_DIR = Path("data/officeqa-raw")
TEXT_DIR = Path("treasury_bulletins_parsed/transformed")
QUESTION_FILES = {"officeqa_pro.csv": 133, "officeqa_full.csv": 246}
EXPECTED_TEXT_FILES = 697


def validate(raw_dir: Path) -> None:
    for filename, expected in QUESTION_FILES.items():
        with (raw_dir / filename).open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not {"uid", "question", "answer"} <= set(reader.fieldnames or []):
                raise ValueError(f"{filename}: required CSV columns are missing")
            rows = list(reader)
        ids = {row["uid"] for row in rows if row.get("uid", "").strip()}
        if len(rows) != expected or len(ids) != expected:
            raise ValueError(f"{filename}: expected {expected} rows with unique, nonempty UIDs")
        print(f"{filename}: {len(rows)} verified questions")

    texts = list((raw_dir / TEXT_DIR).glob("*.txt"))
    if len(texts) != EXPECTED_TEXT_FILES or any(path.stat().st_size == 0 for path in texts):
        raise ValueError(f"Expected {EXPECTED_TEXT_FILES} nonempty corpus text files, found {len(texts)}")
    print(f"Corpus: {len(texts)} text files")


def main() -> None:
    token = get_token()
    if not token:
        raise SystemExit(
            "OfficeQA is gated. Request access at https://huggingface.co/datasets/databricks/officeqa, "
            "then authenticate locally with 'hf auth login' and retry."
        )
    try:
        snapshot_download(
            repo_id=REPO_ID,
            repo_type="dataset",
            revision=REVISION,
            local_dir=RAW_DIR,
            token=token,
            allow_patterns=[
                *QUESTION_FILES,
                (TEXT_DIR / "*.txt").as_posix(),
                "README.md",
                "NOTICE",
                "LICENSE-APACHE",
                "LICENSE-CC-BY-SA",
            ],
        )
    except GatedRepoError:
        raise SystemExit("Hugging Face has not authorized this account/token for OfficeQA.") from None
    except HfHubHTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        raise SystemExit(f"OfficeQA download failed with HTTP status {status}.") from None

    validate(RAW_DIR)
    print(f"Installed OfficeQA at {RAW_DIR} (revision {REVISION})")


if __name__ == "__main__":
    main()
