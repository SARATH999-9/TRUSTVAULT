import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["STORAGE_DIR"] = f"{_tmp}/storage"
os.environ["REQUIRE_DOCUMENT_APPROVAL"] = "false"     # the approval workflow has its own test module
os.environ.pop("ADMIN_EMAIL", None); os.environ.pop("GOOGLE_CLIENT_ID", None)

import shutil  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app import ratelimit  # noqa: E402
from app.models import User  # noqa: E402
from app.security import hash_password  # noqa: E402

PASSWORD = "correct-horse-battery"


@pytest.fixture(autouse=True)
def fresh_db():
    shutil.rmtree(os.environ["STORAGE_DIR"], ignore_errors=True)   # no files leak between tests
    ratelimit.limiter.reset()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def make_user(db):
    def _make(role="viewer", email=None, password=PASSWORD):
        u = User(email=email or f"{role}@example.com", name=role.title(), role=role, status="active",
                 email_verified=True, password_hash=hash_password(password))
        db.add(u)
        db.commit()
        return u
    return _make


@pytest.fixture
def login(client):
    """Returns Authorization headers for a user. Clears the cookie jar so users never bleed together."""
    def _login(email, password=PASSWORD):
        r = client.post("/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        client.cookies.clear()
        return {"Authorization": f"Bearer {r.json()['token']}"}
    return _login
