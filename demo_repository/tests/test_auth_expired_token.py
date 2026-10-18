from auth import app
from fastapi.testclient import TestClient


def test_expired_token_returns_401():
    response = TestClient(app).get(
        "/profile", headers={"Authorization": "Bearer expired"}
    )
    assert response.status_code == 401


def test_expired_token_detail_is_token_expired():
    response = TestClient(app).get(
        "/profile", headers={"Authorization": "Bearer expired"}
    )
    assert response.json() == {"detail": "Token expired"}


def test_missing_authorization_returns_401_unauthorized():
    response = TestClient(app).get("/profile")
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_invalid_authorization_returns_401_unauthorized():
    response = TestClient(app).get(
        "/profile", headers={"Authorization": "Bearer invalid"}
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_valid_token_returns_200_alice():
    response = TestClient(app).get(
        "/profile", headers={"Authorization": "Bearer valid"}
    )
    assert response.status_code == 200
    assert response.json() == {"user": "alice"}
