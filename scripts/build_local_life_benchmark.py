"""Build the versioned GenTrip LocalLifeBench fixture."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from src.evaluation.local_life import build_dataset, poi_coverage_issues  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build GenTrip LocalLifeBench")
    parser.add_argument(
        "--poi-fixture",
        type=Path,
        default=BACKEND / "fixtures" / "pois.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=BACKEND / "fixtures" / "local_life_benchmark.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset = build_dataset()
    poi_fixture = json.loads(args.poi_fixture.read_text(encoding="utf-8"))
    issues = poi_coverage_issues(dataset, poi_fixture)
    if issues:
        raise RuntimeError("POI coverage validation failed: " + "; ".join(issues))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(dataset, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(dataset["metadata"], ensure_ascii=False, indent=2))
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
