"""Regression guard for mobile model-picker ghost clicks."""
from pathlib import Path


SRC = (
    Path(__file__).resolve().parent.parent / "static/js/modelPicker.js"
).read_text(encoding="utf-8")


def test_touch_pointer_toggles_once_and_suppresses_compatibility_click():
    assert "btn.addEventListener('pointerup'" in SRC
    assert "e.pointerType !== 'touch' && e.pointerType !== 'pen'" in SRC
    assert "_ignoreClickUntil = Date.now() + 750" in SRC
    assert "if (Date.now() < _ignoreClickUntil)" in SRC
