import datetime

SEASON_HERO = {
    "spring": {
        "label": "春季賞櫻",
        "tagline": "粉色櫻花正盛開，是走訪日本最浪漫的季節",
        "image_query": "Japan cherry blossom sakura spring pink",
    },
    "summer": {
        "label": "夏日祭典",
        "tagline": "花火大會、浴衣祭典，感受日本夏天的熱鬧氣氛",
        "image_query": "Japan summer festival fireworks night",
    },
    "autumn": {
        "label": "秋季楓紅",
        "tagline": "楓紅銀杏染滿山林，最適合悠閒散策的季節",
        "image_query": "Japan autumn foliage maple leaves temple",
    },
    "winter": {
        "label": "冬季雪景",
        "tagline": "雪國銀白世界，泡湯賞雪一次滿足",
        "image_query": "Japan snow winter onsen mountain",
    },
}


def current_season() -> str:
    month = datetime.date.today().month
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    if month in (9, 10, 11):
        return "autumn"
    return "winter"


def current_season_hero() -> dict:
    return {"season": current_season(), **SEASON_HERO[current_season()]}
