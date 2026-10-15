"""新使用者的預設分類，以及自動分類用的關鍵字。"""

from sqlalchemy.orm import Session

from app.models import EXPENSE, INCOME, Category, User

# (名稱, 圖示, 關鍵字)；關鍵字比對時取「最長命中」，所以「早餐店」會優先於「早餐」
DEFAULT_CATEGORIES: dict[str, list[tuple[str, str, str]]] = {
    EXPENSE: [
        ("餐飲", "🍱", "早餐,午餐,晚餐,宵夜,早午餐,便當,飯,麵,餐,吃,火鍋,燒肉,拉麵,壽司,咖啡,飲料,奶茶,手搖,星巴克,"
                     "麥當勞,肯德基,摩斯,點心,甜點,蛋糕,零食,水果,外送,ubereats,foodpanda,聚餐"),
        ("交通", "🚌", "捷運,公車,計程車,uber,高鐵,台鐵,火車,客運,加油,油錢,停車,悠遊卡,一卡通,etag,過路費,機票,"
                     "腳踏車,youbike,機車,保養,洗車"),
        ("購物", "🛍️", "衣服,褲子,鞋,包包,網購,蝦皮,momo,pchome,淘寶,amazon,3c,手機,電腦,耳機,家電,化妝品,保養品,"
                     "日用品,衛生紙,洗髮精,全聯,家樂福,好市多,costco,大創,無印"),
        ("居家", "🏠", "房租,租金,水費,電費,瓦斯,網路費,管理費,第四台,家具,ikea,修繕,清潔"),
        ("娛樂", "🎮", "電影,唱歌,ktv,遊戲,steam,switch,netflix,spotify,youtube,disney,訂閱,演唱會,展覽,門票,旅遊,"
                     "住宿,飯店,民宿,書,漫畫"),
        ("醫療", "💊", "看醫生,掛號,診所,醫院,藥,牙醫,健檢,眼鏡,保健"),
        ("通訊", "📱", "電話費,手機費,月租費,中華電信,台灣大哥大,遠傳,儲值"),
        ("教育", "📚", "學費,補習,課程,上課,教材,考試,報名費,文具"),
        ("人情", "🎁", "紅包,禮物,禮金,喜帖,奠儀,請客,送禮,捐款"),
        ("保險", "🛡️", "保險,保費,勞保,健保"),
        ("寵物", "🐾", "飼料,貓砂,寵物,獸醫,罐頭"),
        ("其他", "📦", ""),
    ],
    INCOME: [
        ("薪水", "💼", "薪水,薪資,月薪,工資,加班費"),
        ("獎金", "🏆", "獎金,年終,分紅,三節"),
        ("投資", "📈", "股息,股利,利息,配息,投資,賣股,基金,租金收入"),
        ("兼職", "🧑‍💻", "兼職,打工,接案,稿費,外快"),
        ("退款", "↩️", "退款,退費,退稅,回饋,現金回饋"),
        ("其他收入", "💰", ""),
    ],
}

FALLBACK_NAME = {EXPENSE: "其他", INCOME: "其他收入"}


def ensure_default_categories(db: Session, user: User) -> None:
    if db.query(Category).filter(Category.user_id == user.id).first():
        return
    for kind, rows in DEFAULT_CATEGORIES.items():
        for order, (name, icon, keywords) in enumerate(rows):
            db.add(Category(user_id=user.id, kind=kind, name=name, icon=icon, keywords=keywords, sort_order=order))
    db.flush()


def active_categories(db: Session, user: User, kind: str | None = None) -> list[Category]:
    q = db.query(Category).filter(Category.user_id == user.id, Category.archived.is_(False))
    if kind:
        q = q.filter(Category.kind == kind)
    return q.order_by(Category.kind, Category.sort_order, Category.id).all()


def fallback_category(db: Session, user: User, kind: str) -> Category:
    cats = active_categories(db, user, kind)
    for c in cats:
        if c.name == FALLBACK_NAME[kind]:
            return c
    if cats:
        return cats[-1]
    # 使用者把該類分類全部封存了：補回預設的「其他」
    cat = Category(user_id=user.id, kind=kind, name=FALLBACK_NAME[kind], icon="📦", sort_order=99)
    db.add(cat)
    db.flush()
    return cat


def best_match(cats: list[Category], text: str) -> tuple[Category | None, int]:
    """內容命中的最長關鍵字（含分類名稱本身）與其長度。"""
    lowered = text.lower()
    best, best_len = None, 0
    for c in cats:
        for kw in [c.name, *c.keyword_list]:
            k = kw.lower()
            if k and k in lowered and len(k) > best_len:
                best, best_len = c, len(k)
    return best, best_len


def match_hint(cats: list[Category], hint: str) -> Category | None:
    for c in cats:
        if c.name == hint:
            return c
    for c in cats:
        if hint in c.name or c.name in hint:
            return c
    return None


def find_category(db: Session, user: User, kind: str, text: str, explicit: str | None = None) -> Category:
    """依明確指定的分類名（#餐飲）或內容關鍵字找分類，找不到就歸到「其他」。"""
    cats = active_categories(db, user, kind)
    if explicit and (hit := match_hint(cats, explicit)):
        return hit
    return best_match(cats, text)[0] or fallback_category(db, user, kind)
