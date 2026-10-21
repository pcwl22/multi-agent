"""Independent acceptance: not copied into the repair workspace."""

import pytest
from auth import app
from fastapi.testclient import TestClient


@pytest.mark.parametrize("page,expected", [(1, [1, 2]), (2, [3, 4]), (5, [9, 10]), (6, [])])
def test_one_based_page_contract(page, expected):
    response = TestClient(app).get("/items", params={"page": page, "page_size": 2})
    assert response.status_code == 200
    assert response.json() == {"items": expected}


def test_invalid_page_contract():
    assert TestClient(app).get("/items", params={"page": 0}).status_code == 422
