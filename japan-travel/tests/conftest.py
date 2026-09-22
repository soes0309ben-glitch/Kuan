import os
import tempfile

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp_db.name}")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

# Explicit (not setdefault) so tests never pick up real values from a
# developer's local .env — pydantic-settings falls back to reading .env
# directly for anything not already present in the OS environment.
for _key in (
    "STRIPE_SECRET_KEY",
    "UNSPLASH_ACCESS_KEY",
    "NEWSAPI_KEY",
    "RESEND_API_KEY",
    "NOTIFY_EMAIL",
    "NOTIFY_FROM_EMAIL",
    "ADMIN_EMAILS",
):
    os.environ[_key] = ""
