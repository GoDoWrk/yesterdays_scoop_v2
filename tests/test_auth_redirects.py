import asyncio

from fastapi import HTTPException
from starlette.requests import Request

import app.main as main


def _request(path: str, accept: str = "text/html") -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": [(b"accept", accept.encode("utf-8"))],
        "client": ("testclient", 123),
        "server": ("testserver", 80),
        "scheme": "http",
    }
    return Request(scope)


def test_http_401_redirects_html_requests_to_login():
    request = _request("/")
    response = asyncio.run(main.app_http_exception_handler(request, HTTPException(status_code=401, detail="Authentication required")))

    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=%2F"


def test_http_401_returns_json_when_html_not_requested():
    request = _request("/", accept="application/json")
    response = asyncio.run(main.app_http_exception_handler(request, HTTPException(status_code=401, detail="Authentication required")))

    assert response.status_code == 401
    assert b"Authentication required" in response.body


def test_http_401_does_not_redirect_wildcard_accept():
    request = _request("/", accept="*/*")
    response = asyncio.run(main.app_http_exception_handler(request, HTTPException(status_code=401, detail="Authentication required")))

    assert response.status_code == 401
    assert b"Authentication required" in response.body
