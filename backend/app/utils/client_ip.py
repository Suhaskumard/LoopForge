"""Client address behind trusted reverse proxies.

`X-Forwarded-For` is attacker-controlled, so it is honoured only for the last
`TRUSTED_PROXY_COUNT` hops: with N trusted proxies the real client is the Nth entry from the
right (the address the outermost trusted proxy saw). With 0 the header is ignored entirely.
"""

from starlette.requests import Request

from app.config import settings


def client_ip(request: Request) -> str:
    direct = request.client.host if request.client else "-"
    n = settings.trusted_proxy_count
    if n <= 0:
        return direct
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    if len(hops) < n:  # fewer hops than proxies: the header did not come through our chain
        return direct
    return hops[-n]
