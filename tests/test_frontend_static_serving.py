import asyncio

from src.api import app


def get(path: str) -> tuple[int, dict[str, str]]:
    """Make a minimal ASGI GET request without an external HTTP test client."""
    messages: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "root_path": "",
    }
    asyncio.run(app(scope, receive, send))
    start = next(message for message in messages if message["type"] == "http.response.start")
    return start["status"], {key.decode(): value.decode() for key, value in start["headers"]}


def test_frontend_pages_are_served_from_the_api_origin():
    status, headers = get("/")

    assert status == 200
    assert "text/html" in headers["content-type"]

    status, headers = get("/signup.html")
    assert status == 200
    assert "text/html" in headers["content-type"]


def test_frontend_static_directories_are_served():
    status, headers = get("/js/api.js")

    assert status == 200
    assert "javascript" in headers["content-type"]


def test_non_public_frontend_files_are_not_served():
    status, _ = get("/CLAUDE.md")

    assert status == 404
