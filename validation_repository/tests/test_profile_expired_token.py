from auth import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_expired_token_returns_401_with_detail():
    response = client.get("/profile", headers={"Authorization": "Bearer expired"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Token expired"}


def test_valid_token_still_returns_profile():
    response = client.get("/profile", headers={"Authorization": "Bearer valid"})
    assert response.status_code == 200
    assert response.json() == {"user": "alice"}


def test_missing_token_still_returns_401():
    response = client.get("/profile")
    assert response.status_code == 401
