"""Keeps the local server private to the browser tab that opened it.

Caitation listens on 127.0.0.1 and has no login, so any website open in the same browser
could otherwise talk to it: trigger reindexing or Claude requests via cross-site
requests, or, with DNS rebinding (an attacker domain that resolves to 127.0.0.1), even
read search results and PDFs. Two checks close that:

- Host header must be a loopback name (defeats DNS rebinding: the browser sends the
  attacker's domain as Host).
- Requests a browser marks as coming from another site are refused (Sec-Fetch-Site,
  Origin). Clients outside a browser (curl, scripts) send neither and stay allowed.
"""

from starlette.responses import PlainTextResponse

ALLOWED_HOSTNAMES = {"127.0.0.1", "localhost", "[::1]"}


def _hostname(host: str) -> str:
    if host.startswith("["):  # IPv6 literal, e.g. [::1]:8000
        return host.split("]", 1)[0] + "]"
    return host.rsplit(":", 1)[0]


def rejection_reason(headers: dict[str, str]) -> str | None:
    """Why a request with these (lower-cased) headers must be refused, or None."""
    host = headers.get("host", "")
    if _hostname(host).lower() not in ALLOWED_HOSTNAMES:
        return "Caitation nimmt nur Anfragen über 127.0.0.1 oder localhost an."
    fetch_site = headers.get("sec-fetch-site")
    if fetch_site and fetch_site not in ("same-origin", "none"):
        return "Anfragen von anderen Websites sind nicht erlaubt."
    origin = headers.get("origin")
    if origin and origin != f"http://{host}":
        return "Anfragen von anderen Websites sind nicht erlaubt."
    return None


class LocalOnlyMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
            reason = rejection_reason(headers)
            if reason:
                await PlainTextResponse(reason, status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)
