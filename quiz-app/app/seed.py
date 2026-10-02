"""從 JSON 檔匯入題庫到資料庫。

    python -m app.seed seed/*.json

要匯入正式站時，先把 DATABASE_URL 設成 Render Postgres 的 External Database URL。
"""

import json
import sys

from app.catalog import import_questions
from app.db import SessionLocal, init_db


def main(paths: list[str]) -> None:
    if not paths:
        sys.exit("用法：python -m app.seed seed/*.json")
    items = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            items += json.load(f)
    init_db()
    with SessionLocal() as db:
        result = import_questions(db, items)
    print(f"完成：新增 {result['added']} 題，更新 {result['updated']} 題（共讀入 {len(items)} 題）")


if __name__ == "__main__":
    main(sys.argv[1:])
