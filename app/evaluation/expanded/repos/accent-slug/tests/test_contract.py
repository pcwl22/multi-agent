from slugs import slugify


def test_existing_contract():
    assert slugify("Hello, World!") == "hello-world"
    assert slugify("") == ""
