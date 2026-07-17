"""Fallback memory extractor must surface setup / stack / project context.

The LLM extractor is the main path, but obvious durable statements should
survive even when the background model is conservative. The fallback now also
catches environment/stack/workflow cues (the kind of context the user hates
repeating) instead of only name/location/preference/goal.
"""
from services.memory.memory_extractor import _fallback_memory_candidates


def _texts(content):
    cands = _fallback_memory_candidates([{"role": "user", "content": content}])
    return [c["text"].lower() for c in cands]


def test_setup_statement_is_captured():
    texts = _texts("My setup is Windows 11 with PowerShell and neovim")
    assert any("windows 11" in t and "neovim" in t for t in texts)


def test_tool_usage_is_captured():
    texts = _texts("I use uv for python package management")
    assert any("uses uv" in t for t in texts)


def test_stack_is_captured():
    texts = _texts("I develop with FastAPI and SQLAlchemy")
    assert any("develops with fastapi" in t for t in texts)


def test_project_is_captured():
    texts = _texts("I'm building a self-hosted AI workspace called Odysseus")
    assert any("working on" in t and "odysseus" in t for t in texts)


def test_company_is_captured():
    texts = _texts("I work at Acme Corp on the platform team")
    assert any("works at acme corp" in t for t in texts)


def test_fallback_does_not_capture_assistant_messages():
    cands = _fallback_memory_candidates([
        {"role": "assistant", "content": "My setup is Linux and I use vim"},
    ])
    assert cands == []


def test_fallback_cap_allows_up_to_four():
    """A single user message can match several patterns at once; the cap was
    raised from 2 to 4 so more of them survive in one pass."""
    msg = (
        "My name is Sam. I live in Berlin. I use neovim. "
        "I'm building a notes app. I work at Globex."
    )
    cands = _fallback_memory_candidates([{"role": "user", "content": msg}])
    assert len(cands) <= 4
