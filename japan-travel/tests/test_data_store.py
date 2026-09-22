import pytest

from app import data_store

SAMPLE = [
    {
        "id": "fushimi-inari",
        "name_zh": "伏見稻荷大社",
        "name_ja": "伏見稲荷大社",
        "region": "kansai",
        "prefecture": "京都府",
        "category": "attraction",
        "tags": ["神社", "免費景點"],
        "description": "千本鳥居聞名的神社",
        "is_remote_island": False,
    },
    {
        "id": "kerama-snorkel",
        "name_zh": "慶良間群島浮潛",
        "name_ja": "慶良間諸島",
        "region": "okinawa",
        "prefecture": "沖繩縣",
        "category": "attraction",
        "tags": ["離島", "海景"],
        "description": "慶良間藍的絕美海域",
        "is_remote_island": True,
    },
    {
        "id": "dotonbori-takoyaki",
        "name_zh": "道頓堀章魚燒",
        "name_ja": "たこ焼き",
        "region": "kansai",
        "prefecture": "大阪府",
        "category": "food",
        "tags": ["美食", "街頭小吃"],
        "description": "大阪道頓堀必吃章魚燒",
        "is_remote_island": False,
    },
]


@pytest.fixture(autouse=True)
def sample_attractions(monkeypatch):
    monkeypatch.setattr(data_store, "get_attractions", lambda: SAMPLE)


def test_search_by_query_matches_name_and_description():
    results = data_store.search_attractions(query="鳥居")
    assert [r["id"] for r in results] == ["fushimi-inari"]


def test_filter_by_region():
    results = data_store.search_attractions(region="okinawa")
    assert [r["id"] for r in results] == ["kerama-snorkel"]


def test_filter_by_category():
    results = data_store.search_attractions(category="food")
    assert [r["id"] for r in results] == ["dotonbori-takoyaki"]


def test_filter_remote_island_only():
    results = data_store.search_attractions(remote_island_only=True)
    assert [r["id"] for r in results] == ["kerama-snorkel"]


def test_no_filters_returns_all():
    results = data_store.search_attractions()
    assert len(results) == 3
