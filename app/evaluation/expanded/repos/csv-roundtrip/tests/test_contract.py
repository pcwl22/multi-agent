from exporter import export_rows


def test_existing_contract():
    assert export_rows([]) == ""
    assert export_rows([["a", 1], ["b", 2]]) == "a,1\nb,2\n"
