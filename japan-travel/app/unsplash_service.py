import json
import logging
import time
from pathlib import Path

import requests

from app.config import get_settings

logger = logging.getLogger(__name__)

FALLBACK_IMAGE = "/static/img/placeholder.svg"

_HEADERS = {"User-Agent": "japan-travel-app/0.1 (local travel-planning demo project)"}
_TIMEOUT = 8


def _get_with_retry(url: str, params: dict, retries: int = 1) -> requests.Response:
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(0.6 * (attempt + 1))
    raise last_exc

# Persisted so resolved photo URLs survive a server restart — without this,
# every restart would re-pay the Unsplash/Wikipedia network cost for every
# attraction on the next page load. Only successful lookups are persisted
# (see get_photo_url) — a transient network failure must not permanently
# lock an attraction into showing the placeholder forever.
_CACHE_FILE = Path(__file__).resolve().parent.parent / ".cache" / "photo_urls.json"


def _load_cache() -> dict[str, str]:
    try:
        with _CACHE_FILE.open(encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_cache() -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _CACHE_FILE.open("w", encoding="utf-8") as f:
            json.dump(_disk_cache, f, ensure_ascii=False, indent=2)
    except OSError:
        logger.warning("Could not persist photo URL cache to %s", _CACHE_FILE)


# In-memory cache: holds every result (including placeholder) for this
# process's lifetime, so we don't re-hit the network for the same query
# twice in one run even when there's genuinely no photo to find.
_cache: dict[str, str] = {}

# On-disk cache: holds only successful (non-placeholder) results, loaded
# once at import time to seed _cache.
_disk_cache: dict[str, str] = _load_cache()
_cache.update(_disk_cache)


def _unsplash_photo(query: str, width: int) -> str | None:
    settings = get_settings()
    if not settings.unsplash_access_key:
        return None
    try:
        resp = requests.get(
            "https://api.unsplash.com/search/photos",
            params={"query": query, "per_page": 1, "orientation": "landscape"},
            headers={"Authorization": f"Client-ID {settings.unsplash_access_key}"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        results = resp.json().get("results") or []
        if not results:
            return None
        return f"{results[0]['urls']['raw']}&w={width}&q=80&auto=format&fit=crop"
    except requests.RequestException:
        return None


def _wikipedia_photo(query: str, width: int) -> str | None:
    """Keyless fallback: look up a real photo via Wikipedia's public API
    (no account/API key needed) so pages show real scenery before an
    Unsplash key is configured. Each call retries once on failure since
    this shared sandbox's outbound IP sees occasional throttling.
    """
    try:
        search_resp = _get_with_retry(
            "https://en.wikipedia.org/w/api.php",
            {"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": 1},
        )
        hits = search_resp.json().get("query", {}).get("search") or []
        if not hits:
            return None
        title = hits[0]["title"]

        image_resp = _get_with_retry(
            "https://en.wikipedia.org/w/api.php",
            {
                "action": "query",
                "prop": "pageimages",
                "piprop": "thumbnail",
                "pithumbsize": width,
                "titles": title,
                "format": "json",
            },
        )
        pages = image_resp.json().get("query", {}).get("pages", {})
        for page in pages.values():
            thumb = (page.get("thumbnail") or {}).get("source")
            if thumb:
                return thumb
        return None
    except requests.RequestException:
        return None


def _resolve(query: str, width: int) -> str:
    return _unsplash_photo(query, width) or _wikipedia_photo(query, width) or FALLBACK_IMAGE


def _remember(cache_key: str, url: str) -> None:
    _cache[cache_key] = url
    if url != FALLBACK_IMAGE:
        _disk_cache[cache_key] = url
        _save_cache()


def get_photo_url(query: str, width: int = 800) -> str:
    """Return a real photo URL for a search query: Unsplash first (once an
    access key is configured), then a keyless Wikipedia lookup, then a local
    placeholder. Successful results are cached in-process and on disk.
    """
    cache_key = f"{query.lower().strip()}::{width}"
    if cache_key in _cache:
        return _cache[cache_key]

    url = _resolve(query, width)
    _remember(cache_key, url)
    return url
