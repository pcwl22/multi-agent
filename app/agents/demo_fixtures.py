"""Explicit known-bug rules for offline workflow testing; not a general repair model."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DemoFixture:
    markers: tuple[str, ...]
    module: str
    search_terms: tuple[str, ...]
    old: str
    new: str
    regression_path: str
    regression_code: str


FIXTURES = (
    DemoFixture(
        markers=("expired", "过期"),
        module="auth.py",
        search_terms=("expired", "authenticate", "HTTPException"),
        old='status_code=500, detail="Token expired"',
        new='status_code=401, detail="Token expired"',
        regression_path="tests/test_expired_regression.py",
        regression_code=(
            "from fastapi.testclient import TestClient\n"
            "from auth import app\n\n"
            "def test_expired_token_returns_401():\n"
            "    response = TestClient(app).get('/profile', "
            "headers={'Authorization': 'Bearer expired'})\n"
            "    assert response.status_code == 401\n"
            "    assert response.json()['detail'] == 'Token expired'\n"
        ),
    ),
    DemoFixture(
        markers=("pagination", "paginate", "分页"),
        module="pagination.py",
        search_terms=("paginate", "page_size", "start"),
        old="start = page * page_size",
        new="start = (page - 1) * page_size",
        regression_path="tests/test_pagination_regression.py",
        regression_code=(
            "from fastapi.testclient import TestClient\nfrom auth import app\n\n"
            "def test_second_page_uses_one_based_index():\n"
            "    response = TestClient(app).get('/items', params={'page': 2, 'page_size': 2})\n"
            "    assert response.status_code == 200\n"
            "    assert response.json() == {'items': [3, 4]}\n"
        ),
    ),
    DemoFixture(
        markers=("discount", "折扣"),
        module="pricing.py",
        search_terms=("discounted_total", "discount_percent", "round"),
        old="amount * (1 - discount_percent)",
        new="amount * (1 - discount_percent / 100)",
        regression_path="tests/test_discount_regression.py",
        regression_code=(
            "from fastapi.testclient import TestClient\nfrom auth import app\n\n"
            "def test_discount_percent_is_scaled():\n"
            "    response = TestClient(app).get('/price', "
            "params={'amount': 100, 'discount_percent': 20})\n"
            "    assert response.status_code == 200\n"
            "    assert response.json() == {'total': 80}\n"
        ),
    ),
)


def select_fixture(issue: str) -> DemoFixture:
    matches = [
        rule for rule in FIXTURES if any(marker in issue.casefold() for marker in rule.markers)
    ]
    if len(matches) != 1:
        raise ValueError(
            "Mock only accepts one bundled issue: expired token, pagination, or discount"
        )
    return matches[0]
