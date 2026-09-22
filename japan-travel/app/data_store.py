import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

DATA_DIR = Path(__file__).parent / "data"

REGION_LABELS = {
    "hokkaido": "北海道",
    "tohoku": "東北",
    "kanto": "關東",
    "chubu": "中部",
    "kansai": "關西",
    "chugoku": "中國",
    "shikoku": "四國",
    "kyushu": "九州",
    "okinawa": "沖繩及離島",
}

DURATION_LABELS = {
    "3d2n": "3天2夜",
    "4d3n": "4天3夜",
    "5d4n": "5天4夜",
    "6d5n": "6天5夜",
    "7d6n": "7天6夜",
}

TIER_LABELS = {"economy": "經濟型", "comfort": "舒適型", "luxury": "豪華型"}


def _load_json(filename: str) -> list[dict]:
    path = DATA_DIR / filename
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return json.load(f)


@lru_cache
def get_attractions() -> list[dict]:
    return _load_json("attractions.json")


@lru_cache
def get_attractions_by_id() -> dict[str, dict]:
    return {a["id"]: a for a in get_attractions()}


@lru_cache
def get_itineraries() -> list[dict]:
    return _load_json("itineraries.json")


@lru_cache
def get_itineraries_by_id() -> dict[str, dict]:
    return {i["id"]: i for i in get_itineraries()}


def find_attraction(attraction_id: str) -> dict | None:
    return get_attractions_by_id().get(attraction_id)


def find_itinerary(itinerary_id: str) -> dict | None:
    return get_itineraries_by_id().get(itinerary_id)


def search_attractions(
    query: str = "",
    region: str = "",
    category: str = "",
    remote_island_only: bool = False,
) -> list[dict]:
    results = get_attractions()
    query = query.strip().lower()
    if query:
        results = [
            a
            for a in results
            if query in a["name_zh"].lower()
            or query in a.get("name_ja", "").lower()
            or query in a["description"].lower()
            or any(query in t.lower() for t in a.get("tags", []))
            or query in a.get("prefecture", "").lower()
        ]
    if region:
        results = [a for a in results if a["region"] == region]
    if category:
        results = [a for a in results if a["category"] == category]
    if remote_island_only:
        results = [a for a in results if a.get("is_remote_island")]
    return results


def photo_url(image_query: str, width: int = 800) -> str:
    """A same-origin URL that lazily resolves to a real photo. Pages embed
    this directly in <img src>, so photo lookups happen per-image via the
    browser's own (parallel, lazy-loaded) requests instead of blocking the
    page/API response on every attraction's photo before anything renders.
    """
    return f"/api/photo?q={quote(image_query)}&w={width}"


def maps_url(attraction: dict) -> str:
    name = attraction.get("name_ja") or attraction["name_zh"]
    query = f"{name} {attraction.get('prefecture', '')}".strip()
    return f"https://www.google.com/maps/search/?api=1&query={quote(query)}"


def clear_cache() -> None:
    get_attractions.cache_clear()
    get_attractions_by_id.cache_clear()
    get_itineraries.cache_clear()
    get_itineraries_by_id.cache_clear()
