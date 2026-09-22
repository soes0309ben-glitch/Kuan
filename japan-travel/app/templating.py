from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.csrf import get_csrf_token
from app.data_store import DURATION_LABELS, REGION_LABELS, TIER_LABELS, maps_url, photo_url

templates = Jinja2Templates(directory="app/templates")
templates.env.globals["APP_NAME"] = get_settings().app_name
templates.env.globals["REGION_LABELS"] = REGION_LABELS
templates.env.globals["DURATION_LABELS"] = DURATION_LABELS
templates.env.globals["TIER_LABELS"] = TIER_LABELS
templates.env.globals["csrf_token"] = get_csrf_token
templates.env.globals["maps_url"] = maps_url
templates.env.globals["photo_url"] = photo_url
