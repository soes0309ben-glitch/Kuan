import json
import logging
import time
from pathlib import Path

import requests

from app.config import get_settings

logger = logging.getLogger(__name__)

_CACHE_FILE = Path(__file__).resolve().parent.parent / ".cache" / "news.json"
_CACHE_TTL_SECONDS = 24 * 60 * 60  # "每日更新" — refetch at most once every 24h
_HEADERS = {"User-Agent": "japan-travel-app/0.1 (local travel-planning demo project)"}


def _load_cache() -> dict | None:
    try:
        with _CACHE_FILE.open(encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _save_cache(payload: dict) -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _CACHE_FILE.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError:
        logger.warning("Could not persist news cache to %s", _CACHE_FILE)


def _fetch_from_newsapi(api_key: str) -> list[dict]:
    resp = requests.get(
        "https://newsapi.org/v2/everything",
        params={
            "q": "Japan travel OR Japan tourism OR 日本 旅遊 OR 日本 観光",
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 20,
        },
        headers={**_HEADERS, "X-Api-Key": api_key},
        timeout=8,
    )
    resp.raise_for_status()
    articles = resp.json().get("articles", [])
    return [
        {
            "title": a.get("title"),
            "source": (a.get("source") or {}).get("name"),
            "url": a.get("url"),
            "published_at": a.get("publishedAt"),
            "description": a.get("description"),
            "image_url": a.get("urlToImage"),
        }
        for a in articles
        if a.get("title") and a.get("url")
    ]


def get_travel_news() -> dict:
    """Returns {"configured": bool, "articles": [...], "fetched_at": iso-ish, "error": str|None}.
    Cached on disk for _CACHE_TTL_SECONDS so this is a real daily refresh,
    not a fake "every request" call that would burn through API quota.
    """
    settings = get_settings()
    if not settings.newsapi_key:
        return {"configured": False, "articles": [], "fetched_at": None, "error": None}

    cached = _load_cache()
    if cached and (time.time() - cached.get("fetched_unix", 0)) < _CACHE_TTL_SECONDS:
        return {"configured": True, **cached}

    try:
        articles = _fetch_from_newsapi(settings.newsapi_key)
        payload = {"articles": articles, "fetched_unix": time.time(), "fetched_at": time.strftime("%Y-%m-%d %H:%M")}
        _save_cache(payload)
        return {"configured": True, **payload, "error": None}
    except requests.RequestException as exc:
        logger.warning("NewsAPI fetch failed: %s", exc)
        if cached:
            # Serve stale cache rather than an empty page on a transient outage.
            return {"configured": True, **cached, "error": "新聞更新暫時失敗，顯示上次快取內容"}
        return {"configured": True, "articles": [], "fetched_at": None, "error": "新聞來源暫時無法取得，請稍後再試"}
