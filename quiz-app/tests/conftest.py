import os
from pathlib import Path

import pytest

os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(__file__).parent / "test_quiz.db")
os.environ["SECRET_KEY"] = "test-secret"
os.environ["STRIPE_SECRET_KEY"] = "sk_test_dummy"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
os.environ["ADMIN_EMAILS"] = "admin@example.com"

from fastapi import Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.catalog import import_questions  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.dependencies import get_current_user  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402


def sample_questions():
    qs = []
    for cat in ("anime", "travel"):
        for diff in ("easy", "medium", "hard"):
            for i in range(6):
                qs.append({"cat": cat, "type": "single", "difficulty": diff, "q": f"{cat}-{diff}-單選{i}",
                           "options": ["對", "錯1", "錯2", "錯3"], "answer": "對", "explain": "說明"})
            for i in range(3):
                qs.append({"cat": cat, "type": "short", "difficulty": diff, "q": f"{cat}-{diff}-簡答{i}",
                           "accept": ["富士山", "fuji"]})
            qs.append({"cat": cat, "type": "qa", "difficulty": diff, "q": f"{cat}-{diff}-問答", "ref": "參考答案"})
            qs.append({"cat": cat, "type": "image", "difficulty": diff, "q": f"{cat}-{diff}-圖片",
                       "img": "fuji.jpg", "options": ["富士山", "玉山"], "answer": "富士山"})
    return qs


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = SessionLocal()
    import_questions(session, sample_questions())
    yield session
    session.close()


@pytest.fixture()
def make_client(db):
    """建立已登入的測試用戶端（跳過 Google 登入流程）。"""

    session = SessionLocal()

    def current_user(request: Request):
        # 每個測試用戶端用 X-Test-User 標頭帶自己的身分，多位使用者才不會互相覆蓋；
        # 沒帶標頭就是未登入。每次請求重新讀取並結束交易，避免長時間占用連線。
        uid = request.headers.get("x-test-user")
        session.expire_all()
        found = session.get(User, int(uid)) if uid else None
        session.commit()
        return found

    app.dependency_overrides[get_current_user] = current_user

    def _make(email="player@example.com", subscribed=False):
        user = User(google_sub=email, email=email, name=email.split("@")[0],
                    subscription_status="active" if subscribed else "none", stripe_customer_id=f"cus_{email}")
        db.add(user)
        db.commit()
        return TestClient(app, headers={"x-test-user": str(user.id)}), user.id

    yield _make
    app.dependency_overrides.clear()
    # 測試結束一定要關閉，否則連線池會被用光，後面的測試卡住直到逾時
    session.close()
