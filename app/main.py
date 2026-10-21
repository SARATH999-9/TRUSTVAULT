from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import models  # noqa: F401  (register tables)
from .bootstrap import ensure_admin, warn_if_no_admin
from .db import Base, SessionLocal, check_schema, engine
from .deps import COOKIE
from .config import settings
from .routes import admin, auth, documents, grants, policy, suggestions


@asynccontextmanager
async def lifespan(app: FastAPI):
    check_schema()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        ensure_admin(db)          # first administrator from ADMIN_EMAIL / ADMIN_PASSWORD
        warn_if_no_admin(db)
    yield


app = FastAPI(title="TrustVault", version="0.2.0", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(documents.router)
app.include_router(grants.router)
app.include_router(suggestions.router)
app.include_router(policy.router)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def web_app():
    """The single-page web app (all assets are same-origin, so the strict CSP below applies)."""
    return FileResponse(STATIC_DIR / "index.html")


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# No inline script/style, no third-party origins, no framing, no <base> tricks.
STRICT_CSP = "default-src 'self'; img-src 'self' blob:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"


def app_csp() -> str:
    """The web app's CSP. Only when Google sign-in is configured does it also allow Google's sign-in script,
    frame, API and stylesheet, each limited to the exact /gsi/ paths Google documents."""
    if not settings.google_client_id:
        return STRICT_CSP
    g = "https://accounts.google.com/gsi/"
    return (f"default-src 'self'; img-src 'self' blob:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; "
            f"script-src 'self' {g}client; frame-src {g}; connect-src 'self' {g}; style-src 'self' {g}style")


@app.middleware("http")
async def csrf_and_headers(request: Request, call_next):
    # CSRF: a state-changing request authenticated by COOKIE (no Authorization header) must come
    # from our own origin. Bearer-token API clients are not exposed to CSRF. SameSite=Strict is the 2nd layer.
    if request.method not in SAFE_METHODS and request.cookies.get(COOKIE) \
            and not request.headers.get("authorization"):
        src = request.headers.get("origin") or request.headers.get("referer")
        if not src or urlparse(src).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Cross-origin request blocked"}, status_code=403)
    # Cheap early rejection of oversized bodies (the route also enforces the cap on bytes actually read).
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > (settings.max_upload_mb + 1) * 1024 * 1024:
        return JSONResponse({"detail": "Request too large"}, status_code=413)
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store"
    if request.url.path in ("/docs", "/redoc"):      # interactive API docs need the Swagger/Redoc CDN assets
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: "
            "https://fastapi.tiangolo.com; worker-src blob:; frame-ancestors 'none'")
    elif request.url.path == "/":
        resp.headers["Content-Security-Policy"] = app_csp()
    else:
        resp.headers["Content-Security-Policy"] = STRICT_CSP
    return resp


@app.get("/health")
def health():
    return {"status": "ok"}
