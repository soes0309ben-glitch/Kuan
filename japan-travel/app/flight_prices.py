import datetime

# 從台灣出發、桃園/高雄進出的來回經濟艙機票參考價格區間（新台幣）。
# 這是「行前抓預算」用的粗估區間，不是即時比價，實際票價會依訂票時間、
# 航空公司、艙等大幅浮動——頁面上務必清楚標示這一點。
REGION_AIRPORTS = {
    "hokkaido": "新千歲機場（札幌）",
    "tohoku": "仙台機場",
    "kanto": "東京（成田／羽田）",
    "chubu": "中部國際機場（名古屋）",
    "kansai": "關西機場（大阪）",
    "chugoku": "廣島機場",
    "shikoku": "高松機場",
    "kyushu": "福岡機場",
    "okinawa": "那霸機場",
}

SEASONAL_FLIGHT_PRICES_TWD = {
    "hokkaido": {"low": (9000, 13000), "mid": (13000, 18000), "high": (18000, 28000)},
    "tohoku": {"low": (8000, 12000), "mid": (12000, 16000), "high": (16000, 24000)},
    "kanto": {"low": (7000, 10000), "mid": (10000, 14000), "high": (14000, 22000)},
    "chubu": {"low": (7500, 11000), "mid": (11000, 15000), "high": (15000, 23000)},
    "kansai": {"low": (6500, 9500), "mid": (9500, 13000), "high": (13000, 20000)},
    "chugoku": {"low": (9000, 13000), "mid": (13000, 17000), "high": (17000, 25000)},
    "shikoku": {"low": (10000, 14000), "mid": (14000, 18000), "high": (18000, 26000)},
    "kyushu": {"low": (7500, 11000), "mid": (11000, 15000), "high": (15000, 22000)},
    "okinawa": {"low": (7000, 10500), "mid": (10500, 14500), "high": (14500, 21000)},
}

BAND_LABELS = {
    "low": "淡季",
    "mid": "平季",
    "high": "旺季（櫻花／暑假／楓葉／跨年前後）",
}

_HIGH_MONTHS = {3, 4, 7, 8, 10, 11, 12}
_LOW_MONTHS = {1, 2}


def current_season_band() -> str:
    month = datetime.date.today().month
    if month in _HIGH_MONTHS:
        return "high"
    if month in _LOW_MONTHS:
        return "low"
    return "mid"


def flight_price_info(region: str) -> dict | None:
    prices = SEASONAL_FLIGHT_PRICES_TWD.get(region)
    if not prices:
        return None
    return {
        "airport": REGION_AIRPORTS.get(region, ""),
        "current_band": current_season_band(),
        "bands": [
            {"key": key, "label": BAND_LABELS[key], "low": lo, "high": hi}
            for key, (lo, hi) in prices.items()
        ],
    }
