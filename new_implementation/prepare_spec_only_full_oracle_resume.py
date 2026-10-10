#!/usr/bin/env python3
"""Package a validated partial full-oracle run as a private Kaggle resume input."""
from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PUBLISH = ROOT / "kaggle_upload_spec_only_full_oracle_resume" / "dataset_publish"


def locate_optional(root: Path, name: str) -> Path | None:
    matches = list(root.rglob(name))
    if len(matches) > 1:
        raise RuntimeError(f"Multiple {name} files below {root}: {matches}")
    return matches[0] if matches else None


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-output", required=True, type=Path)
    args = parser.parse_args()
    files = {
        name: locate_optional(args.run_output, name)
        for name in ["qwen_candidates.jsonl", "llama_candidates.jsonl"]
    }
    if not any(files.values()):
        raise RuntimeError(f"No resumable candidate JSONL found below {args.run_output}")
    expected = {"qwen_candidates.jsonl": 312, "llama_candidates.jsonl": 468}
    PUBLISH.mkdir(parents=True, exist_ok=True)
    archive_path = PUBLISH / "active_tb_s_oracle_full_checkpoint.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        manifest = {}
        for name, path in files.items():
            if path is None:
                continue
            data = rows(path)
            keys = {(str(row["task_id"]), int(row["candidate_index"])) for row in data}
            if len(keys) != len(data) or len(data) > expected[name]:
                raise RuntimeError(f"Invalid partial checkpoint {path}: {len(data)} rows")
            archive.write(path, name)
            manifest[name] = {
                "rows": len(data),
                "compiled": sum(bool(row.get("compiled")) for row in data),
                "expected_rows": expected[name],
            }
        archive.writestr("resume_manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
    (PUBLISH / "dataset-metadata.json").write_text(json.dumps({
        "title": "ACTIVE-TB-S Full Oracle Resume v1",
        "id": "tishaferdous/active-tb-s-oracle-full-resume-v1",
        "licenses": [{"name": "MIT"}],
    }, indent=2), encoding="utf-8")
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip() is not None or any("\\" in name for name in archive.namelist()):
            raise RuntimeError("Invalid resume archive")
    print("Built", archive_path, archive_path.stat().st_size)


if __name__ == "__main__":
    main()
