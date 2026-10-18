from auth import app
from fastapi.testclient import TestClient
from pagination import paginate


def test_empty_pagination():
    assert paginate([], 1, 2) == []


def test_invalid_page_is_rejected():
    assert TestClient(app).get("/items", params={"page": 0}).status_code == 422


def test_zero_discount_preserves_amount():
    assert TestClient(app).get("/price", params={"amount": 100}).json() == {"total": 100}
