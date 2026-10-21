import pytest
from slugs import slugify


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Café déjà vu", "cafe-deja-vu"),
        ("cafe\u0301", "cafe"),
        ("Ångström", "angstrom"),
        ("Hello, World!", "hello-world"),
        ("---", ""),
    ],
)
def test_slug(value, expected):
    assert slugify(value) == expected
