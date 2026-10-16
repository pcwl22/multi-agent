"""Independent acceptance: percentages use the 0..100 scale."""

import pytest
from auth import app
from fastapi.testclient import TestClient


@pytest.mark.parametrize("discount,expected", [(0, 100), (20, 80), (100, 0)])
def test_discount_contract(discount, expected):
    response = TestClient(app).get("/price", params={"amount": 100, "discount_percent": discount})
    assert response.status_code == 200
    assert response.json() == {"total": expected}


def test_invalid_discount_contract():
    assert (
        TestClient(app).get("/price", params={"amount": 100, "discount_percent": 101}).status_code
        == 422
    )
