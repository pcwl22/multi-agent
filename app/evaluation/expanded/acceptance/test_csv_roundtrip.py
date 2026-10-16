import csv
import io

import pytest
from exporter import export_rows


@pytest.mark.parametrize(
    "rows", [[["a,b", "c"]], [['say "hi"', "line\nbreak"]], [["中文", "é,ø"], ["", "x"]]]
)
def test_roundtrip(rows):
    assert list(csv.reader(io.StringIO(export_rows(rows)))) == rows


def test_simple():
    assert export_rows([]) == ""
    assert export_rows([["a", 1]]) == "a,1\n"
