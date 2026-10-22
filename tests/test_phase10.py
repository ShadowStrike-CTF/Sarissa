# Sarissa — Phase 10: inline favicon + visibility-gated probes. Sarissa-side HTML/JS only.
# © 2026 ShadowStrike. MIT License.
# Aut Viam Inveniam Aut Faciam

import base64
import re

import pytest
from fastapi.testclient import TestClient

from sarissa.main import create_app

DATA_URI = "data:image/svg+xml;base64,"


@pytest.fixture
def html(tmp_path):
    with TestClient(create_app(sessions_dir=tmp_path)) as c:
        r = c.get("/")
    assert r.status_code == 200
    return r.text


def favicon_href(page):
    return re.search(r'<link rel="icon" href="([^"]*)"', page).group(1)


def test_favicon_present(html):
    head = html[:html.index("</head>")]
    assert '<link rel="icon"' in head


def test_favicon_base64(html):
    href = favicon_href(html)
    assert href.startswith(DATA_URI)
    svg = base64.b64decode(href[len(DATA_URI):], validate=True).decode("utf-8")
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert "#922b21" in svg, "Sarissa crimson"
    for banned in ("href", "<image", "<script", "url("):
        assert banned not in svg, f"favicon must be self-contained: {banned}"


def test_treska_probe_visibility_gate(html):
    body = html[html.index("async function treskaStatus()"):]
    body = body[:body.index("\n}\n")]
    gate = body.index("document.visibilityState")
    assert gate < body.index("fetch("), "visibility checked before any probe fetch"
    assert 'addEventListener("visibilitychange"' in html
    timer = re.search(r"setInterval\(.*?, 15000\)", html).group(0)
    assert "document.visibilityState" in timer, "15 s session refresh is visibility-gated too"
