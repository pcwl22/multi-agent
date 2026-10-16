from auth import app
from fastapi.testclient import TestClient


def test_valid_token():
    assert TestClient(app).get("/profile", headers={"Authorization": "Bearer valid"}).json() == {
        "user": "alice"
    }


def test_missing_token():
    assert TestClient(app).get("/profile").status_code == 401
