"""Regression guards for frontend updates appearing after a normal reload."""
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SW = (ROOT / "static/sw.js").read_text(encoding="utf-8")
INDEX = (ROOT / "static/index.html").read_text(encoding="utf-8")
APP = (ROOT / "app.py").read_text(encoding="utf-8")


def test_service_worker_uses_network_first_without_http_cache():
    assert "await fetch(e.request, { cache: 'no-store' })" in SW
    assert "fetch(e.request, { cache: 'no-store' }).then" in SW
    assert "return cached || network" not in SW


def test_service_worker_update_check_bypasses_cache():
    assert "updateViaCache: 'none'" in INDEX
    assert "await registration.update()" in INDEX


def test_service_worker_migrates_legacy_scope_and_reloads_on_takeover():
    assert "navigator.serviceWorker.getRegistrations()" in INDEX
    assert "pathname === '/static/'" in INDEX
    assert "registration.unregister()" in INDEX
    assert "scope: '/'" in INDEX
    assert "'controllerchange'" in INDEX
    assert "window.location.reload()" in INDEX


def test_static_source_assets_are_not_stored_by_browser():
    assert 'resp.headers["Cache-Control"] = "no-store"' in APP
    assert 'resp.headers["Service-Worker-Allowed"] = "/"' in APP
