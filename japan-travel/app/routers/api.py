from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from app.data_store import REGION_LABELS, maps_url, photo_url, search_attractions
from app.unsplash_service import get_photo_url

router = APIRouter(prefix="/api")


@router.get("/attractions")
def api_search_attractions(
    q: str = "", region: str = "", category: str = "", remote_island: str = ""
):
    # A plain `bool` query param rejects an empty string with 422 — accept
    # a string instead and coerce leniently, since "" (unchecked checkbox)
    # is exactly what the front end sends by default.
    remote_island_only = remote_island.lower() in ("true", "1", "yes", "on")
    results = search_attractions(
        query=q, region=region, category=category, remote_island_only=remote_island_only
    )
    return {
        "count": len(results),
        "results": [
            {
                **a,
                "region_label": REGION_LABELS.get(a["region"], a["region"]),
                "image_url": photo_url(a["image_query"]),
                "maps_url": maps_url(a),
            }
            for a in results
        ],
    }


@router.get("/photo")
def photo_redirect(q: str, w: int = 800):
    """Resolves one attraction's photo on demand and redirects to it.
    Cached (in-process + on disk) after the first resolution, so repeat
    requests for the same query are effectively instant.
    """
    return RedirectResponse(get_photo_url(q, w), status_code=302)
