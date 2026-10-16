"""Evaluator-owned holdout. Never supplied to the repair model."""

from auth import app
from fastapi.testclient import TestClient


def test_expired_token_contract():
    response = TestClient(app).get("/profile", headers={"Authorization": "Bearer expired"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Token expired"}


def test_valid_token_contract():
    response = TestClient(app).get("/profile", headers={"Authorization": "Bearer valid"})
    assert response.status_code == 200
    assert response.json() == {"user": "alice"}


def test_missing_token_contract():
    assert TestClient(app).get("/profile").status_code == 401
