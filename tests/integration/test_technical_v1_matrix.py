import pytest

from merval_agent.evaluation_technical_v1 import evaluate_case, load_cases


@pytest.mark.parametrize("case", load_cases(), ids=lambda c: c["id"])
def test_technical_v1_http_matrix(case, tmp_path):
    row = evaluate_case(case, tmp_path / case["id"])
    assert "FAIL" not in row["axes"].values(), row
