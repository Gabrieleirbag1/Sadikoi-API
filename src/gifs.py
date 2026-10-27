import re

import requests
from flask_login import current_user
from lite_logging.lite_logging import log

from config import KLIPY_API_KEY

KLIPY_BASE_URL = "https://api.klipy.com/api/v1"
KLIPY_TIMEOUT_SECONDS = 5
GIFS_PER_PAGE = 50
MAX_QUERY_LENGTH = 100
SLUG_PATTERN = re.compile(r'^[A-Za-z0-9_-]{1,200}$')

def _klipy(method: str, path: str, **kwargs):
    """Call Klipy with the server-side key; returns (content, None) or (None, (body, status))."""
    if not KLIPY_API_KEY:
        return None, ({"success": False, "message": "GIF service is not configured"}, 503)
    try:
        response = requests.request(
            method, f"{KLIPY_BASE_URL}/{KLIPY_API_KEY}/gifs/{path}",
            timeout=KLIPY_TIMEOUT_SECONDS, **kwargs,
        )
        response.raise_for_status()
        return response.json(), None
    except (requests.RequestException, ValueError) as error:
        # The URL (which contains the key) is never logged: only the exception type.
        log(f"Klipy request failed ({path.split('/')[0]}): {type(error).__name__}", level="ERROR")
        return None, ({"success": False, "message": "GIF service unavailable"}, 502)

def _gifs(payload) -> list:
    data = (payload or {}).get("data") or {}
    return data.get("data") or []

def get_trending_gifs():
    payload, error = _klipy("GET", "trending")
    if error:
        return error
    return {"success": True, "content": _gifs(payload)}, 200

def get_recent_gifs():
    payload, error = _klipy("GET", f"recent/{current_user.id}", params={"per_page": GIFS_PER_PAGE})
    if error:
        return error
    return {"success": True, "content": _gifs(payload)}, 200

def search_gifs(request):
    query = (request.args.get("q") or "").strip()
    if not query or len(query) > MAX_QUERY_LENGTH:
        return {"success": False, "message": f"q is required (max {MAX_QUERY_LENGTH} characters)"}, 400
    params = {"q": query, "per_page": GIFS_PER_PAGE, "content_filter": "medium", "customer_id": str(current_user.id)}
    payload, error = _klipy("GET", "search", params=params)
    if error:
        return error
    return {"success": True, "content": _gifs(payload)}, 200

def share_gif(slug: str):
    """Tell Klipy a GIF was sent (their trending/recent rankings rely on it)."""
    if not SLUG_PATTERN.match(slug):
        return {"success": False, "message": "Invalid GIF slug"}, 400
    _, error = _klipy("POST", f"share/{slug}", json={"customer_id": str(current_user.id)})
    if error:
        return error
    return {"success": True}, 200
