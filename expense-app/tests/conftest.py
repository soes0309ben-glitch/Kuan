import base64
import hashlib
import hmac
import json
import os
from pathlib import Path

import pytest

os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(__file__).parent / "test_expense.db")
os.environ["SECRET_KEY"] = "test-secret"
os.environ["LINE_CHANNEL_SECRET"] = "line-secret"
os.environ["LINE_CHANNEL_ACCESS_TOKEN"] = "line-token"
os.environ["CRON_TOKEN"] = "cron-token"
os.environ["BASE_URL"] = "https://expense.example.com"
for _key in ("LINE_LOGIN_CHANNEL_ID", "LINE_LOGIN_CHANNEL_SECRET", "LINE_BOT_ADD_FRIEND_URL"):
    os.environ[_key] = ""
os.environ["DEV_LOGIN"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app import line_api  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

LINE_USER = "U" + "a" * 32


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def line(db, monkeypatch):
    """模擬 LINE：攔下 reply / push，送出已簽章的 webhook 事件。"""
    sent = {"reply": [], "push": []}
    monkeypatch.setattr(line_api, "reply", lambda token, msgs: sent["reply"].append(msgs) or True)
    monkeypatch.setattr(line_api, "push", lambda to, msgs: sent["push"].append((to, msgs)) or True)
    monkeypatch.setattr(line_api, "get_profile", lambda uid: {"displayName": "小明", "pictureUrl": ""})
    client = TestClient(app)

    def send(event: dict, user: str = LINE_USER):
        event = {"replyToken": "rt", "source": {"type": "user", "userId": user}, **event}
        body = json.dumps({"events": [event]}).encode()
        sig = base64.b64encode(hmac.new(b"line-secret", body, hashlib.sha256).digest()).decode()
        r = client.post("/line/webhook", content=body, headers={"x-line-signature": sig,
                                                                 "content-type": "application/json"})
        assert r.status_code == 200, r.text
        return sent["reply"][-1] if sent["reply"] else None

    def say(text: str, user: str = LINE_USER):
        return send({"type": "message", "message": {"type": "text", "text": text}}, user)

    def postback(data: str, user: str = LINE_USER):
        return send({"type": "postback", "postback": {"data": data}}, user)

    send.say, send.postback, send.sent, send.client = say, postback, sent, client
    return send


@pytest.fixture()
def web(line):
    """透過 LINE 的「網頁」魔法連結登入網頁版。"""
    msgs = line.say("網頁")
    uri = msgs[0]["contents"]["footer"]["contents"][0]["action"]["uri"]
    client = TestClient(app, base_url="https://expense.example.com")
    r = client.get(uri.replace("https://expense.example.com", ""), follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    return client
