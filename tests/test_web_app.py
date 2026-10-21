"""The web app must obey the same strict rules as the API: same-origin only, no inline code, no HTML-string sinks."""
import pathlib
import re

from app.config import settings
from app.main import STRICT_CSP

STATIC = pathlib.Path(__file__).resolve().parent.parent / "static"
JS_FILES = sorted(STATIC.rglob("*.js"))


def test_root_serves_the_app_with_strict_headers(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert r.headers["content-security-policy"] == STRICT_CSP
    assert r.headers["x-frame-options"] == "DENY" and r.headers["x-content-type-options"] == "nosniff"
    assert "TrustVault" in r.text


def test_index_html_has_no_inline_script_style_or_handlers():
    html = (STATIC / "index.html").read_text()
    assert re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(?!\s*</script>)", html) == []
    assert "<style" not in html and not re.search(r"\sstyle=", html)
    assert not re.search(r"\son[a-z]+\s*=", html)
    assert "http://" not in html and "https://" not in html          # nothing third-party


def test_javascript_never_builds_html_from_strings_or_stores_sessions():
    assert JS_FILES, "no JS found"
    banned = ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function",
              'setAttribute("style"', "localStorage", "sessionStorage", "http://", "https://"]
    for f in JS_FILES:
        text = f.read_text().replace("https://accounts.google.com/gsi/client", "").replace("http://www.w3.org/2000/svg", "")
        # ^ the one allowed third-party script, and the SVG XML namespace id (an identifier, not a request)
        for b in banned:
            assert b not in text, f"{f.name} contains {b!r}"


def test_static_files_are_served_and_directory_traversal_is_blocked(client):
    assert client.get("/static/js/main.js").status_code == 200
    assert client.get("/static/css/app.css").status_code == 200
    for p in ("/static/../app/config.py", "/static/%2e%2e/app/config.py", "/static/..%2fapp%2fconfig.py",
              "/static/js/../../app/config.py", "/static//etc/passwd", "/static/"):
        r = client.get(p)
        assert r.status_code in (400, 404), p
        assert "database_url" not in r.text, p


def test_health_reveals_nothing_about_configuration(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_no_demo_credentials_or_demo_login_shortcuts_ship_in_the_app():
    for f in list(STATIC.rglob("*.js")) + list(STATIC.rglob("*.html")):
        text = f.read_text()
        for bad in ("TrustVault-Demo", "DEMO_PASSWORD", "trustvault.demo", "Demo accounts"):
            assert bad not in text, f"{f.name} contains {bad!r}"
    root = STATIC.parent
    assert "seed" not in (root / "start.sh").read_text().lower()
    assert "SEED" not in (root / "render.yaml").read_text() and "seed" not in (root / "Dockerfile").read_text().lower()


def test_seed_script_refuses_to_run_without_an_explicit_development_flag(tmp_path):
    import subprocess, sys
    env = {"PATH": "/usr/bin:/bin", "DATABASE_URL": f"sqlite:///{tmp_path}/x.db", "STORAGE_DIR": str(tmp_path / "s")}
    out = subprocess.run([sys.executable, str(STATIC.parent / "scripts" / "seed.py")], capture_output=True, text=True, env=env, cwd=STATIC.parent)
    assert "Refusing to seed" in out.stdout


def test_csp_allows_google_sign_in_only_when_configured_and_only_on_the_app_page(client, monkeypatch):
    assert client.get("/").headers["content-security-policy"] == STRICT_CSP
    monkeypatch.setattr(settings, "google_client_id", "cid.apps.googleusercontent.com")
    csp = client.get("/").headers["content-security-policy"]
    assert "script-src 'self' https://accounts.google.com/gsi/client" in csp and "frame-src https://accounts.google.com/gsi/" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp and "frame-ancestors 'none'" in csp
    assert client.get("/health").headers["content-security-policy"] == STRICT_CSP          # API stays locked down
    assert client.get("/static/js/main.js").headers["content-security-policy"] == STRICT_CSP


def test_old_databases_get_a_clear_error_instead_of_a_crash(tmp_path):
    import pytest
    from sqlalchemy import create_engine, text
    from app.db import check_schema
    eng = create_engine(f"sqlite:///{tmp_path}/old.db")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY, email VARCHAR(254), is_active BOOLEAN)"))
    with pytest.raises(RuntimeError, match="older version"):
        check_schema(eng)
    check_schema(create_engine(f"sqlite:///{tmp_path}/fresh.db"))             # empty database is fine
