from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_demo_renders_without_backend():
    demo = AppTest.from_file(str(Path(__file__).parents[2] / "frontend/demo.py"))
    demo.run(timeout=15)
    assert not demo.exception
    assert demo.title[0].value.startswith("RepoPilot")
    assert demo.text_area[0].label == "Bug 描述"
