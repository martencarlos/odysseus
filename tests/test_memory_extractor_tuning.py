"""Tuning knobs on auto memory extraction.

extract_and_store() gained keyword-only params (max_facts, context_window,
dedup_threshold) so the recall aggressiveness is UI-configurable instead of
hardcoded. These pin that the knobs actually flow into:
  - the extraction system prompt (max_facts cap)
  - how many recent messages are analyzed (context_window)
  - the vector + text dedup thresholds (dedup_threshold)
"""

import asyncio
import tempfile

import pytest

import src.llm_core
import src.event_bus
from src.memory import MemoryManager
import services.memory.memory_extractor as _extractor
from services.memory.memory_extractor import (
    extract_and_store,
    _is_text_duplicate,
    _extract_system_prompt,
)


@pytest.fixture(autouse=True)
def _reset_audit_counter(monkeypatch):
    # The audit trigger reads a module-global counter; keep tests isolated so
    # one test's additions can't trip an audit in another.
    monkeypatch.setattr(_extractor, "_extractions_since_audit", 0)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _FakeSession:
    owner = "alice"
    session_id = "sess-1"

    def __init__(self, messages):
        self._messages = messages

    def get_context_messages(self):
        return list(self._messages)


class _RecordingVectorStore:
    """Captures the threshold passed to find_similar; never matches."""

    healthy = True

    def __init__(self):
        self.seen_thresholds = []

    def find_similar(self, text, threshold=0.72):
        self.seen_thresholds.append(threshold)
        return None

    def add(self, memory_id, text):
        return None


def test_extract_system_prompt_interpolates_max_facts():
    assert "UP TO 3 facts" in _extract_system_prompt(3)
    assert "UP TO 6 facts" in _extract_system_prompt(6)


def test_extract_and_store_passes_max_facts_into_prompt(monkeypatch):
    captured = {}

    async def _fake_llm(url, model, messages, **kwargs):
        captured["system"] = next(
            m["content"] for m in messages if m["role"] == "system"
        )
        return "[]"

    monkeypatch.setattr(src.llm_core, "llm_call_async", _fake_llm)
    monkeypatch.setattr(src.event_bus, "fire_event", lambda *a, **k: None)

    with tempfile.TemporaryDirectory() as data_dir:
        _run(extract_and_store(
            _FakeSession([
                {"role": "user", "content": "I use neovim on Arch."},
                {"role": "assistant", "content": "Cool."},
            ]),
            MemoryManager(data_dir),
            None,
            endpoint_url="http://x", model="m", headers=None,
            max_facts=8,
        ))

    assert "UP TO 8 facts" in captured["system"]


def test_extract_and_store_respects_context_window(monkeypatch):
    """A small context_window must keep older messages OUT of the transcript
    sent to the LLM — otherwise tuning the window does nothing and the model
    re-analyzes stale turns every run."""
    captured = {}

    async def _fake_llm(url, model, messages, **kwargs):
        captured["transcript"] = next(
            m["content"] for m in messages if m["role"] == "user"
        )
        return "[]"

    monkeypatch.setattr(src.llm_core, "llm_call_async", _fake_llm)
    monkeypatch.setattr(src.event_bus, "fire_event", lambda *a, **k: None)

    messages = [
        {"role": "user", "content": "MSG-ONE-OLD"},
        {"role": "assistant", "content": "reply-one"},
        {"role": "user", "content": "MSG-TWO"},
        {"role": "assistant", "content": "reply-two"},
        {"role": "user", "content": "MSG-THREE-RECENT"},
        {"role": "assistant", "content": "reply-three"},
    ]

    with tempfile.TemporaryDirectory() as data_dir:
        _run(extract_and_store(
            _FakeSession(messages),
            MemoryManager(data_dir),
            None,
            endpoint_url="http://x", model="m", headers=None,
            context_window=2,
        ))

    assert "MSG-THREE-RECENT" in captured["transcript"]
    assert "MSG-ONE-OLD" not in captured["transcript"]


def test_extract_and_store_forwards_dedup_threshold_to_vector_dedup(monkeypatch):
    async def _fake_llm(url, model, messages, **kwargs):
        return '[{"text": "Alice lives in Lisbon", "category": "fact"}]'

    monkeypatch.setattr(src.llm_core, "llm_call_async", _fake_llm)
    monkeypatch.setattr(src.event_bus, "fire_event", lambda *a, **k: None)

    vec = _RecordingVectorStore()
    with tempfile.TemporaryDirectory() as data_dir:
        _run(extract_and_store(
            _FakeSession([
                {"role": "user", "content": "I live in Lisbon."},
                {"role": "assistant", "content": "Noted."},
            ]),
            MemoryManager(data_dir),
            vec,
            endpoint_url="http://x", model="m", headers=None,
            dedup_threshold=0.85,
        ))

    assert vec.seen_thresholds, "find_similar was never called"
    assert all(t == 0.85 for t in vec.seen_thresholds)


def test_is_text_duplicate_threshold_controls_outcome():
    """Higher threshold = stricter = keeps more (fewer near-duplicates dropped)."""
    existing = [{"text": "User likes small pull requests"}]
    new_text = "User likes small pull requests a lot"

    # Default (0.6): Jaccard overlap is high enough to count as a duplicate.
    assert _is_text_duplicate(new_text, existing) is True
    # Stricter (0.9): the same overlap no longer clears the bar -> kept.
    assert _is_text_duplicate(new_text, existing, threshold=0.9) is False
