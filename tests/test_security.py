import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from backend.security import LocalOnlyMiddleware, rejection_reason


@pytest.mark.parametrize(
    "headers",
    [
        {"host": "127.0.0.1:8000"},
        {"host": "localhost:8000"},
        {"host": "[::1]:8000"},
        {"host": "127.0.0.1:8000", "sec-fetch-site": "same-origin", "origin": "http://127.0.0.1:8000"},
        {"host": "localhost:8000", "sec-fetch-site": "none"},  # URL typed into the address bar
    ],
)
def test_allows_local_requests(headers):
    assert rejection_reason(headers) is None


@pytest.mark.parametrize(
    "headers",
    [
        {"host": "evil.example:8000"},  # DNS rebinding: attacker domain resolving to 127.0.0.1
        {"host": "127.0.0.1.evil.example"},
        {"host": ""},
        {"host": "127.0.0.1:8000", "sec-fetch-site": "cross-site"},
        {"host": "127.0.0.1:8000", "sec-fetch-site": "same-site"},  # other app on another port
        {"host": "127.0.0.1:8000", "origin": "https://evil.example"},
        {"host": "127.0.0.1:8000", "origin": "http://127.0.0.1:3000"},
        {"host": "127.0.0.1:8000", "origin": "null"},
    ],
)
def test_rejects_foreign_requests(headers):
    assert rejection_reason(headers) is not None


@pytest.fixture
def client():
    app = Starlette(routes=[Route("/", lambda request: PlainTextResponse("ok"), methods=["GET", "POST"])])
    app.add_middleware(LocalOnlyMiddleware)
    return TestClient(app, base_url="http://127.0.0.1:8000")


def test_middleware_passes_local_and_blocks_cross_site(client):
    assert client.get("/").text == "ok"
    blocked = client.post("/", headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"})
    assert blocked.status_code == 403
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 403


def test_app_uses_the_middleware():
    from backend.main import app

    assert any(m.cls is LocalOnlyMiddleware for m in app.user_middleware)
