"""docs/API.md must list every endpoint, so the 'who may call this' table cannot silently go stale."""
import pathlib
import re

from fastapi.routing import APIRoute

from app.main import STRICT_CSP, app


def test_api_md_lists_exactly_the_real_endpoints():
    text = (pathlib.Path(__file__).resolve().parent.parent / "docs" / "API.md").read_text()
    documented = set(re.findall(r"\| `([A-Z]+)` \| `([^`]+)` \|", text))
    real = {(m, r.path) for r in app.routes if isinstance(r, APIRoute) for m in r.methods if m not in ("HEAD", "OPTIONS")}
    assert documented == real, (documented ^ real)


def test_interactive_docs_work_but_other_pages_keep_the_strict_csp(client):
    assert "cdn.jsdelivr.net" in client.get("/docs").headers["content-security-policy"]
    assert client.get("/health").headers["content-security-policy"] == STRICT_CSP
