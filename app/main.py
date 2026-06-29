import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import db
from app.config import get_settings

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# 2048: the de-facto URL length limit honoured by most browsers and proxies.
MAX_URL_LENGTH = 2048


def _reserved_route_codes(app: FastAPI) -> frozenset[str]:
    """Leading path segment of every fixed route ("shorten", "admin", ...).

    A generated short code must avoid these, or the route would intercept the
    path before the /{code} catch-all. Derived from the live route table so a
    newly added route reserves its name automatically.
    """
    codes = set()
    for route in app.routes:
        segment = getattr(route, "path", "/").lstrip("/").split("/", 1)[0]
        if segment and "{" not in segment:
            codes.add(segment)
    return frozenset(codes)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db(reserved_codes=_reserved_route_codes(app))
    yield


app = FastAPI(title="Link Shortener", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def normalize_url(raw: str) -> str:
    """Validate and normalise a user-submitted URL.

    Raises ValueError with a user-facing message if the URL is empty, is not an
    http/https URL with a host, or carries embedded credentials.
    """
    candidate = raw.strip()
    if not candidate:
        raise ValueError("Please enter a URL.")
    if len(candidate) > MAX_URL_LENGTH:
        raise ValueError(f"That URL is too long (max {MAX_URL_LENGTH} characters).")
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Enter a valid http:// or https:// URL.")
    # Reject userinfo e.g. ("https://trusted.com@evil.com")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs with embedded credentials aren't allowed.")
    return candidate


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


# Defined with `def` (not `async def`): the SQLite calls below are blocking, so
# FastAPI runs this in a worker thread and the event loop stays responsive.
@app.post("/shorten", response_class=HTMLResponse)
def shorten(request: Request, url: str = Form("")):
    def render(context: dict, status_code: int = 200):
        return templates.TemplateResponse(
            request, "index.html", context, status_code=status_code
        )

    try:
        normalized = normalize_url(url)
    except ValueError as exc:
        return render({"error": str(exc), "url": url}, status_code=400)
    try:
        code = db.get_or_create(normalized)
    except RuntimeError, sqlite3.Error:
        return render(
            {
                "error": "We couldn't create your short link right now. Please try again.",
                "url": normalized,
            },
            status_code=500,
        )
    short_url = f"{get_settings().base_url}/{code}"
    return render({"short_url": short_url, "url": normalized})


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# Declared before the catch-all `/{code}` route below so it isn't shadowed.
@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    return templates.TemplateResponse(request, "admin.html", {"links": db.list_all()})


@app.post("/admin/delete")
def admin_delete(code: str = Form("")):
    db.delete(code)
    return RedirectResponse("/admin", status_code=303)


@app.get("/{code}")
def redirect(request: Request, code: str):
    url = db.lookup(code)
    if url is None:
        return templates.TemplateResponse(request, "404.html", {}, status_code=404)
    return RedirectResponse(url, status_code=302)
