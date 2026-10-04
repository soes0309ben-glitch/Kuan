"""個人檔案：暱稱、頭像（Google／表情符號／上傳圖片）、頭像框、主題色。"""

import base64
import binascii

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import require_json, require_user
from app.models import Profile, User

router = APIRouter(prefix="/api/profile")

FRAMES = ("none", "ribbon", "heart", "star", "flower", "crown", "rainbow")
COLORS = ("pink", "lavender", "mint", "sky", "peach", "lemon",
          "coral", "cherry", "rosegold", "orange", "caramel", "cocoa", "matcha", "teal", "ocean", "midnight", "grape", "slate")
AVATAR_TYPES = ("google", "emoji", "upload")
MAX_AVATAR_BYTES = 300 * 1024
# 只接受常見圖片格式，並用檔頭確認真的是圖片
IMAGE_SIGNATURES = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/webp": (b"RIFF",),
}


def get_profile(db: Session, user: User) -> Profile:
    profile = db.get(Profile, user.id)
    if not profile:
        profile = Profile(user_id=user.id)
        db.add(profile)
        db.flush()
    return profile


def profile_dict(user: User, profile: Profile | None) -> dict:
    p = profile or Profile(nickname="", avatar_type="google", avatar_emoji="", frame="none", color="pink")
    avatar_url = user.picture or ""
    if p.avatar_type == "upload" and p.avatar_data:
        # 加上更新時間避免瀏覽器快取到舊圖
        avatar_url = f"/api/profile/avatar?v={int(p.updated_at.timestamp()) if p.updated_at else 0}"
    return {
        "nickname": p.nickname or "",
        "avatar_type": p.avatar_type,
        "avatar_emoji": p.avatar_emoji or "",
        "avatar_url": avatar_url,
        "frame": p.frame,
        "color": p.color,
        "has_upload": bool(p.avatar_data),
    }


class ProfileBody(BaseModel):
    nickname: str = ""
    avatar_type: str = "google"
    avatar_emoji: str = ""
    frame: str = "none"
    color: str = "pink"


@router.post("", dependencies=[Depends(require_json)])
def update_profile(body: ProfileBody, user: User = Depends(require_user), db: Session = Depends(get_db)):
    if body.frame not in FRAMES or body.color not in COLORS or body.avatar_type not in AVATAR_TYPES:
        raise HTTPException(400, "頭像框、顏色或頭像類型不正確")
    nickname = body.nickname.strip()
    if len(nickname) > 20:
        raise HTTPException(400, "暱稱最多 20 個字")
    emoji = body.avatar_emoji.strip()
    if body.avatar_type == "emoji" and not (0 < len(emoji) <= 8):
        raise HTTPException(400, "請選擇一個表情符號")
    profile = get_profile(db, user)
    if body.avatar_type == "upload" and not profile.avatar_data:
        raise HTTPException(400, "請先上傳頭像圖片")
    profile.nickname = nickname
    profile.avatar_type = body.avatar_type
    profile.avatar_emoji = emoji
    profile.frame = body.frame
    profile.color = body.color
    db.commit()
    return profile_dict(user, profile)


class AvatarBody(BaseModel):
    data_url: str


def decode_image(data_url: str, max_bytes: int) -> tuple[str, bytes]:
    """解析 data URL，只接受 PNG／JPEG／WebP，並用檔頭確認真的是圖片。"""
    header, _, encoded = data_url.partition(",")
    mime = header.removeprefix("data:").removesuffix(";base64")
    if mime not in IMAGE_SIGNATURES or not header.endswith(";base64"):
        raise HTTPException(400, "只支援 PNG、JPEG、WebP 圖片")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "圖片資料格式錯誤")
    if len(data) > max_bytes:
        raise HTTPException(400, "圖片太大了，請選小一點的圖片")
    if not data.startswith(IMAGE_SIGNATURES[mime]) or (mime == "image/webp" and data[8:12] != b"WEBP"):
        raise HTTPException(400, "檔案內容不是有效的圖片")
    return mime, data


@router.post("/avatar", dependencies=[Depends(require_json)])
def upload_avatar(body: AvatarBody, user: User = Depends(require_user), db: Session = Depends(get_db)):
    mime, data = decode_image(body.data_url, MAX_AVATAR_BYTES)
    profile = get_profile(db, user)
    profile.avatar_data = data
    profile.avatar_mime = mime
    profile.avatar_type = "upload"
    db.commit()
    return profile_dict(user, profile)


@router.get("/avatar")
def my_avatar(user: User = Depends(require_user), db: Session = Depends(get_db)):
    profile = db.get(Profile, user.id)
    if not profile or not profile.avatar_data:
        raise HTTPException(404)
    return Response(
        profile.avatar_data,
        media_type=profile.avatar_mime,
        headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"},
    )
