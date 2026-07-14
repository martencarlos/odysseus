"""Shared image-capable model discovery.

Used by:
  - routes/gallery/gallery_routes.py (``/api/gallery/image-models`` — the
    Generate tab's model picker)
  - src/ai_interaction.py (``do_generate_image`` auto-detect)

Keeping this in one place means the model picker and the auto-detect path
agree on exactly which models are considered "image-capable", instead of the
picker showing models auto-detect would never actually pick (or vice versa).
"""

import json as _json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Name-pattern fallback for endpoints where we can't query an authoritative
# capabilities API (anything that isn't OpenRouter). Matches image-generation
# model families across OpenAI, Google, and common open-weight diffusion
# models so they're not lost if run through OpenAI-compatible proxies.
IMAGE_MODEL_NAME_PATTERNS = (
    # OpenAI / ChatGPT image models
    "gpt-image", "dall-e", "chatgpt-image",
    # Google Gemini image-generation variants
    "gemini-2.0-flash-preview-image", "gemini-2.5-flash-image",
    "gemini-2.0-flash-image", "gemini-image", "gemini-3-pro-image",
    # Diffusion model families (local / hosted)
    "flux", "sdxl", "stable-diffusion", "stable_diffusion",
    "sd-", "sd1-", "sd2-", "sd3-", "sd3.",
    "playground-v", "playground-v2", "playground-v3",
    "kolors", "ideogram", "recraft", "seedream", "seed-",
    "leonardo", "dreamshaper", "realvis", "juggernaut",
    "pixart", "auraflow", "ssd-",
)


def looks_like_image_model(model_id: str) -> bool:
    """Name-based heuristic for "is this an image-generation model".

    Used only as a fallback when an authoritative capabilities API (like
    OpenRouter's) isn't available for the endpoint.
    """
    if not model_id:
        return False
    low = model_id.lower()
    # Explicit "image" tag in the name (e.g. google/gemini-2.5-flash-image,
    # openai/gpt-image-1, ...-image-generation).
    if "image" in low or "-img" in low or "_img" in low:
        return True
    return any(low.startswith(p) or p in low for p in IMAGE_MODEL_NAME_PATTERNS)


# ---------------------------------------------------------------------------
# OpenRouter authoritative image-model list. Pattern-matching a generic
# OpenRouter catalog produced a picker full of models that 404 or error on
# generation (most OpenRouter models are text-only). OpenRouter exposes a
# dedicated endpoint that lists exactly the models its Image API supports —
# use that instead of guessing from the name when the endpoint is OpenRouter.
# ---------------------------------------------------------------------------
_OPENROUTER_IMAGE_MODELS_URL = "https://openrouter.ai/api/v1/models"
_or_cache: Dict[str, Any] = {"ids": None, "time": 0.0}
_OR_CACHE_TTL = 600  # seconds


def _fetch_openrouter_image_model_ids(api_key: Optional[str]) -> Optional[List[str]]:
    """Return the list of model ids OpenRouter actually supports for image
    generation, or None on any failure (caller falls back to name matching).
    Cached briefly since this is a slow-changing catalog.
    """
    now = time.time()
    if _or_cache["ids"] is not None and (now - _or_cache["time"]) < _OR_CACHE_TTL:
        return _or_cache["ids"]
    try:
        import httpx

        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        resp = httpx.get(
            _OPENROUTER_IMAGE_MODELS_URL,
            params={"output_modalities": "image"},
            headers=headers,
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        items = (data.get("data") or []) if isinstance(data, dict) else (data or [])
        ids: List[str] = [m["id"] for m in items if isinstance(m, dict) and m.get("id")]
        if ids:
            _or_cache["ids"] = ids
            _or_cache["time"] = now
            return ids
    except Exception as e:
        logger.info("OpenRouter image-model catalog fetch failed: %s", e)
    return None


def _is_openrouter_base(base_url: str) -> bool:
    try:
        from src.llm_core import _host_match
        return _host_match(base_url, "openrouter.ai")
    except Exception:
        return "openrouter.ai" in (base_url or "")


def _parse_cached_models(cached: Optional[str]) -> List[str]:
    if not cached:
        return []
    try:
        parsed = _json.loads(cached)
        if isinstance(parsed, list):
            return [m for m in parsed if isinstance(m, str)]
        if isinstance(parsed, str):
            return [m.strip() for m in parsed.split(",") if m.strip()]
    except Exception:
        pass
    return []


def discover_image_models(owner: Optional[str] = None, session_factory=None) -> List[Dict[str, str]]:
    """Scan the caller's enabled endpoints and return image-capable models.

    Each entry: {id, label, model, source, kind}. ``kind`` is "local" for
    model_type == "image" endpoints, otherwise "provider". De-duplicated by
    model id (case-insensitive), first match wins.

    ``session_factory`` lets callers (and tests) supply the exact SessionLocal
    they're using — e.g. gallery_routes' module-level SessionLocal, which
    tests monkeypatch to a test database. Defaults to src.database.SessionLocal.
    """
    from src.auth_helpers import owner_filter
    from core.database import ModelEndpoint

    if session_factory is None:
        from src.database import SessionLocal as session_factory  # noqa: N813

    out: List[Dict[str, str]] = []
    seen: set = set()

    def _add(label: str, model_id: str, source: str, kind: str) -> None:
        key = (model_id or "").lower()
        if not model_id or key in seen:
            return
        seen.add(key)
        out.append({
            "id": model_id, "label": label or model_id, "model": model_id,
            "source": source, "kind": kind,
        })

    db = session_factory()
    try:
        q = db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True)  # noqa: E712
        q = owner_filter(q, ModelEndpoint, owner)
        eps = q.all()
        for ep in eps:
            ep_name = (getattr(ep, "name", None) or "").strip() or "Local"
            ep_type = (getattr(ep, "model_type", None) or "llm").strip()
            base_url = getattr(ep, "base_url", "") or ""
            is_image_endpoint = ep_type == "image"

            if is_image_endpoint:
                model_ids = _parse_cached_models(getattr(ep, "cached_models", None))
                if not model_ids:
                    model_ids = [ep_name]
                for mid in model_ids:
                    _add(f"{mid} ({ep_name})", mid, ep_name, "local")
                continue

            if _is_openrouter_base(base_url):
                or_ids = _fetch_openrouter_image_model_ids(getattr(ep, "api_key", None))
                if or_ids is not None:
                    for mid in or_ids:
                        _add(f"{mid} ({ep_name})", mid, ep_name, "provider")
                    continue
                # Fall through to name-pattern matching if the catalog fetch failed.

            for mid in _parse_cached_models(getattr(ep, "cached_models", None)):
                if looks_like_image_model(mid):
                    _add(f"{mid} ({ep_name})", mid, ep_name, "provider")
    finally:
        db.close()

    return out
