"""Download and adapt the official TravelPlanner dataset for GenTrip."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
RAW_DIR = ROOT / "data" / "travelplanner" / "raw"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from src.evaluation.travelplanner import (  # noqa: E402
    build_derived_cases,
    build_local_poi_fixture,
    load_reference_records,
    load_source_records,
)


BASE_URL = "https://huggingface.co/datasets/osunlp/TravelPlanner/resolve/main"
FILES = {
    "train.csv": (1306372, "2c02c4a31bf08599ea84013565a05d9a1a0a1b0c7613ded0ca932fb964780da1"),
    "validation.csv": (4833771, "0e54b26b13c0b6d50e8683765e930bffca949488c44634e530da899914d40e80"),
    "train_ref_info.jsonl": (1197800, "f9eff8c9e3056c726c4bc46b8183a51efdf63760755b0183fa36f1c9f14b6e83"),
    "validation_ref_info.jsonl": (5052714, "0555348b457226a7cff866a7ec1962b60105fd90bb9e5c030b9e9ec3f2aff1d0"),
}


def verify_source(path: Path, source_name: str | None = None) -> bool:
    expected_size, expected_digest = FILES[source_name or path.name]
    if not path.exists() or path.stat().st_size != expected_size:
        return False
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest == expected_digest


def download_sources(raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        target = raw_dir / name
        if verify_source(target):
            continue
        print(f"downloading {name}")
        temporary = target.with_suffix(target.suffix + ".part")
        urllib.request.urlretrieve(f"{BASE_URL}/{name}?download=true", temporary)
        if not verify_source(temporary, name):
            temporary.unlink(missing_ok=True)
            raise RuntimeError(f"checksum mismatch for {name}")
        temporary.replace(target)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a GenTrip-derived TravelPlanner suite.")
    parser.add_argument("--download", action="store_true", help="Download official train/validation files")
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--split", choices=("train", "validation"), default="validation")
    parser.add_argument("--samples-per-cell", type=int, default=2)
    parser.add_argument("--seed", default="gentrip-v1")
    parser.add_argument(
        "--output",
        type=Path,
        default=BACKEND / "fixtures" / "travelplanner_gentrip_validation.json",
    )
    parser.add_argument(
        "--poi-output",
        type=Path,
        default=BACKEND / "fixtures" / "travelplanner_pois.json",
        help="Write the isolated local POI fixture",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.samples_per_cell < 1:
        raise SystemExit("--samples-per-cell must be positive")
    if args.download:
        download_sources(args.raw_dir)
    source = args.raw_dir / f"{args.split}.csv"
    if not source.exists():
        raise SystemExit(f"missing {source}; rerun with --download")
    if not verify_source(source):
        raise SystemExit(f"source integrity check failed for {source}; rerun with --download")

    records = load_source_records(source)
    cases = build_derived_cases(
        records,
        split=args.split,
        samples_per_cell=args.samples_per_cell,
        seed=args.seed,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    reference_source = args.raw_dir / f"{args.split}_ref_info.jsonl"
    if not reference_source.exists() or not verify_source(reference_source):
        raise SystemExit(f"reference source integrity check failed for {reference_source}; rerun with --download")
    references = load_reference_records(reference_source)
    poi_fixture = build_local_poi_fixture(cases, references)
    args.poi_output.parent.mkdir(parents=True, exist_ok=True)
    args.poi_output.write_text(json.dumps(poi_fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(cases)} cases to {args.output}")
    print(f"wrote {len(poi_fixture['pois'])} evaluation POIs to {args.poi_output}")
    print("protocol=gentrip-derived-v1 official_travelplanner_score=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
