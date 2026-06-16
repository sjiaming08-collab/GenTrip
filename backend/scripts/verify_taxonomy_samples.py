#!/usr/bin/env python3
"""验收 category taxonomy 映射 — 可独立运行，也可由 pytest 调用。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from tests.taxonomy_sample_cases import run_all_sample_cases  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="验证 taxonomy 映射样例")
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        metavar="ID",
        help="只跑指定用例 id（可重复），默认跑全部",
    )
    parser.add_argument("--limit", type=int, default=10, help="每条召回 POI 上限")
    parser.add_argument("-q", "--quiet", action="store_true", help="仅输出摘要")
    args = parser.parse_args()

    all_results = run_all_sample_cases(limit=args.limit)
    if args.cases:
        selected = set(args.cases)
        all_results = [r for r in all_results if r.case.id in selected]
        missing = selected - {r.case.id for r in all_results}
        if missing:
            print(f"未知用例 id: {', '.join(sorted(missing))}", file=sys.stderr)
            return 2

    passed = sum(1 for r in all_results if r.passed)
    failed = len(all_results) - passed

    for result in all_results:
        case = result.case
        status = "PASS" if result.passed else "FAIL"
        if args.quiet:
            print(f"[{status}] {case.id}: {case.description}")
            continue

        print(f"\n{'=' * 60}")
        print(f"[{status}] {case.id} — {case.description}")
        print(
            f"  district={case.district!r} purpose={case.purpose!r} "
            f"preferred={case.preferred_cuisines!r}"
        )
        print(f"  relax_step: {result.relax_step}")
        print(f"  final_leaves: {result.final_leaves}")
        print(f"  categories: {result.categories}")
        if result.assumptions:
            print(f"  assumptions: {result.assumptions}")
        if result.errors:
            for err in result.errors:
                print(f"  ERROR: {err}")

    print(f"\n{'=' * 60}")
    print(f"合计: {passed} passed, {failed} failed / {len(all_results)} total")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
