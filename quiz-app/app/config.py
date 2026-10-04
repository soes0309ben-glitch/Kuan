import hashlib
import logging
import secrets
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "知識大挑戰"
    secret_key: str = ""
    database_url: str = "sqlite:///./quiz.db"
    base_url: str = "http://127.0.0.1:8000"

    google_client_id: str = ""
    google_client_secret: str = ""

    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id: str = ""
    # 沒設定 STRIPE_PRICE_ID 時使用的月費（新台幣）
    monthly_price_twd: int = 399

    admin_emails: str = ""
    # 選填：設定後可用 X-Import-Token 標頭匯入題庫（不需登入），用完請從環境變數刪除
    import_token: str = ""

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.secret_key.strip():
        # 隨機產生的密鑰每次重啟都會變，Google 登入途中若剛好重啟（部署、免費方案休眠喚醒）
        # 就會「登入驗證失敗」。所以優先用已設定的其他機密推導出固定值；都沒有才隨機產生。
        material = "|".join(
            v for v in (settings.google_client_secret, settings.stripe_secret_key, settings.database_url)
            if v and not v.startswith("sqlite")
        )
        if material:
            settings.secret_key = hashlib.sha256(f"quiz-app-session|{material}".encode()).hexdigest()
            logger.warning("SECRET_KEY 未設定，已由其他機密推導出固定值。建議另外設定 SECRET_KEY。")
        else:
            settings.secret_key = secrets.token_hex(32)
            logger.warning("SECRET_KEY 未設定，已暫時隨機產生（重啟後需重新登入）。正式上線前請設定 SECRET_KEY。")
    return settings
