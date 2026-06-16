"""taxonomy 映射样例 — 自动化验收（数据驱动）。"""

import pytest

from tests.taxonomy_sample_cases import TAXONOMY_SAMPLE_CASES, run_sample_case


@pytest.mark.parametrize(
    "case",
    TAXONOMY_SAMPLE_CASES,
    ids=[c.id for c in TAXONOMY_SAMPLE_CASES],
)
def test_taxonomy_sample_case(case):
    result = run_sample_case(case)
    assert result.passed, (
        f"{case.id}: {result.errors}; "
        f"relax={result.relax_step} categories={result.categories}"
    )
