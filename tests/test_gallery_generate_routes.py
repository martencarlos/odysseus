"""Tests for the gallery image-generation routes (/api/gallery/image-models
and /api/gallery/generate).

Validates:
  - /api/gallery/image-models is owner-scoped (only lists the caller's local
    image endpoints + resolvable cloud models) and returns [] for a null user
    when auth is enabled (fail-closed).
  - /api/gallery/generate creates a GalleryImage, auto-creates / reuses the
    "generated" album, and assigns the image to it.
"""

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import core.database as cdb
from core.database import GalleryAlbum, GalleryImage, ModelEndpoint
import routes.gallery_routes as gallery_routes


def _client(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'gallery.db'}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    cdb.Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(gallery_routes, "SessionLocal", session_factory)
    app = FastAPI()
    app.include_router(gallery_routes.setup_gallery_routes())
    return TestClient(app), session_factory


def test_image_models_owner_scoped(monkeypatch, tmp_path):
    client, sf = _client(monkeypatch, tmp_path)
    # Seed two image endpoints owned by different users.
    db = sf()
    try:
        db.add_all([
            ModelEndpoint(
                id="ep-alice", name="Alice Local", base_url="http://localhost:8001/v1",
                is_enabled=True, model_type="image", owner="alice",
                cached_models='["sdxl-base"]',
            ),
            ModelEndpoint(
                id="ep-bob", name="Bob Local", base_url="http://localhost:8002/v1",
                is_enabled=True, model_type="image", owner="bob",
                cached_models='["flux-dev"]',
            ),
        ])
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(gallery_routes, "get_current_user", lambda r: "alice")
    # Cloud resolution is mocked out: no endpoint → _resolve_model raises ValueError.
    monkeypatch.setattr(
        "src.ai_interaction._resolve_model",
        lambda spec, owner=None: (_ for _ in ()).throw(ValueError("not found")),
    )

    res = client.get("/api/gallery/image-models")
    assert res.status_code == 200
    models = res.json()["models"]
    ids = [m["model"] for m in models]
    assert "sdxl-base" in ids
    assert "flux-dev" not in ids  # bob's endpoint is hidden from alice


def test_image_models_surfaces_llm_endpoint_image_models(monkeypatch, tmp_path):
    # Image-capable models living on a generic LLM endpoint (e.g. OpenRouter)
    # must be surfaced, while non-image models on the same endpoint are not.
    client, sf = _client(monkeypatch, tmp_path)
    db = sf()
    try:
        db.add(ModelEndpoint(
            id="ep-openrouter", name="OpenRouter", base_url="https://openrouter.ai/api/v1",
            is_enabled=True, model_type="llm", owner="alice",
            cached_models='["google/gemini-2.5-flash-image","openai/gpt-4o","black-forest-labs/flux-1-dev","meta-llama/llama-3.1-70b-instruct","openai/gpt-image-1"]',
        ))
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(gallery_routes, "get_current_user", lambda r: "alice")
    monkeypatch.setattr(
        "src.ai_interaction._resolve_model",
        lambda spec, owner=None: (_ for _ in ()).throw(ValueError("not found")),
    )
    # No live network access in tests — force the OpenRouter catalog fetch to
    # "fail" so discovery falls back to name-pattern matching on this
    # endpoint's cached_models, same as any other generic LLM endpoint.
    monkeypatch.setattr(
        "src.image_models._fetch_openrouter_image_model_ids",
        lambda api_key: None,
    )

    res = client.get("/api/gallery/image-models")
    assert res.status_code == 200
    ids = {m["model"] for m in res.json()["models"]}
    # Image-capable models are listed...
    assert "google/gemini-2.5-flash-image" in ids
    assert "black-forest-labs/flux-1-dev" in ids
    assert "openai/gpt-image-1" in ids
    # ...and plain text models are not.
    assert "openai/gpt-4o" not in ids
    assert "meta-llama/llama-3.1-70b-instruct" not in ids


def test_image_models_uses_openrouter_authoritative_catalog(monkeypatch, tmp_path):
    # When the live OpenRouter image-model catalog is available, use it
    # instead of name-pattern guessing — it's exact, so a model that doesn't
    # match our patterns (but IS in the catalog) should still show up, and a
    # model that matches our patterns but ISN'T in the catalog should not.
    client, sf = _client(monkeypatch, tmp_path)
    db = sf()
    try:
        db.add(ModelEndpoint(
            id="ep-openrouter", name="OpenRouter", base_url="https://openrouter.ai/api/v1",
            is_enabled=True, model_type="llm", owner="alice",
            cached_models='["some/totally-unguessable-name","black-forest-labs/flux-1-dev"]',
        ))
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(gallery_routes, "get_current_user", lambda r: "alice")
    monkeypatch.setattr(
        "src.ai_interaction._resolve_model",
        lambda spec, owner=None: (_ for _ in ()).throw(ValueError("not found")),
    )
    monkeypatch.setattr(
        "src.image_models._fetch_openrouter_image_model_ids",
        lambda api_key: ["some/totally-unguessable-name"],
    )

    res = client.get("/api/gallery/image-models")
    assert res.status_code == 200
    ids = {m["model"] for m in res.json()["models"]}
    # Not name-matchable, but present in the live catalog — must be listed.
    assert "some/totally-unguessable-name" in ids
    # Name-matchable, but NOT in the live catalog — must be excluded (the
    # catalog is authoritative once it's available).
    assert "black-forest-labs/flux-1-dev" not in ids


def test_image_models_null_user_single_user_mode(monkeypatch, tmp_path):
    # In auth-disabled / single-user mode, owner_filter is a no-op for a null
    # user, so image endpoints are visible. This mirrors the existing gallery
    # image-generation routes (ai_upscale / style_transfer / inpaint) which
    # share the same _visible_image_endpoint_query helper.
    monkeypatch.delenv("AUTH_ENABLED", raising=False)
    client, sf = _client(monkeypatch, tmp_path)
    db = sf()
    try:
        db.add(ModelEndpoint(
            id="ep-x", name="Local", base_url="http://localhost:8001/v1",
            is_enabled=True, model_type="image", owner=None,
            cached_models='["sdxl-base"]',
        ))
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(gallery_routes, "get_current_user", lambda r: None)
    monkeypatch.setattr(
        "src.ai_interaction._resolve_model",
        lambda spec, owner=None: (_ for _ in ()).throw(ValueError("not found")),
    )

    res = client.get("/api/gallery/image-models")
    assert res.status_code == 200
    ids = [m["model"] for m in res.json()["models"]]
    assert "sdxl-base" in ids  # shared endpoint visible in single-user mode


def test_generate_creates_generated_album(monkeypatch, tmp_path):
    client, sf = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(gallery_routes, "get_current_user", lambda r: "alice")
    monkeypatch.setattr(
        gallery_routes, "require_privilege",
        lambda request, priv: "alice",
    )

    # Mock do_generate_image so it writes a GalleryImage row (mirroring the real
    # helper's persistence) and returns the structured result the route expects.
    async def fake_generate(content, session_id=None, owner=None):
        db = sf()
        try:
            fname = f"{uuid.uuid4().hex}.png"
            img_id = str(uuid.uuid4())
            db.add(GalleryImage(
                id=img_id, filename=fname, prompt="a cat", model="gpt-image-1",
                size="1024x1024", quality="medium", owner=owner, is_active=True,
            ))
            db.commit()
            return {
                "image_url": f"/api/generated-image/{fname}",
                "image_id": img_id,
                "image_model": "gpt-image-1",
                "image_size": "1024x1024",
                "image_quality": "medium",
            }
        finally:
            db.close()

    monkeypatch.setattr("src.ai_interaction.do_generate_image", fake_generate)

    res = client.post("/api/gallery/generate", json={
        "prompt": "a cat", "size": "square", "quality": "medium",
    })
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["ok"] is True
    assert data["model"] == "gpt-image-1"
    image_id = data["image_id"]
    assert image_id

    # The image should now be assigned to a "generated" album owned by alice.
    db = sf()
    try:
        img = db.query(GalleryImage).filter(GalleryImage.id == image_id).one()
        assert img.album_id is not None
        album = db.query(GalleryAlbum).filter(GalleryAlbum.id == img.album_id).one()
        assert album.name == "generated"
        assert album.owner == "alice"
    finally:
        db.close()


def test_generate_reuses_existing_generated_album(monkeypatch, tmp_path):
    client, sf = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(gallery_routes, "get_current_user", lambda r: "alice")
    monkeypatch.setattr(gallery_routes, "require_privilege", lambda request, priv: "alice")

    # Pre-create the "generated" album for alice.
    db = sf()
    try:
        db.add(GalleryAlbum(id="gen-alice", name="generated", owner="alice"))
        db.commit()
    finally:
        db.close()

    async def fake_generate(content, session_id=None, owner=None):
        db2 = sf()
        try:
            fname = f"{uuid.uuid4().hex}.png"
            img_id = str(uuid.uuid4())
            db2.add(GalleryImage(
                id=img_id, filename=fname, prompt="dog", model="gpt-image-1",
                size="1024x1024", quality="medium", owner=owner, is_active=True,
            ))
            db2.commit()
            return {"image_url": f"/api/generated-image/{fname}", "image_id": img_id,
                    "image_model": "gpt-image-1", "image_size": "1024x1024",
                    "image_quality": "medium"}
        finally:
            db2.close()

    monkeypatch.setattr("src.ai_interaction.do_generate_image", fake_generate)

    res = client.post("/api/gallery/generate", json={"prompt": "dog"})
    assert res.status_code == 200, res.text
    image_id = res.json()["image_id"]

    db = sf()
    try:
        img = db.query(GalleryImage).filter(GalleryImage.id == image_id).one()
        assert img.album_id == "gen-alice"  # reused, not a new album
        # Only one generated album should exist for alice.
        albums = db.query(GalleryAlbum).filter(
            GalleryAlbum.name == "generated", GalleryAlbum.owner == "alice"
        ).all()
        assert len(albums) == 1
    finally:
        db.close()


def test_generate_requires_prompt(monkeypatch, tmp_path):
    client, _ = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(gallery_routes, "get_current_user", lambda r: "alice")
    monkeypatch.setattr(gallery_routes, "require_privilege", lambda request, priv: "alice")
    res = client.post("/api/gallery/generate", json={"prompt": ""})
    assert res.status_code == 400
