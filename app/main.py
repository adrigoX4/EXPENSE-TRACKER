from __future__ import annotations

import html
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError, OperationalError

from app import __version__, accounts, seo, security
from app.config import settings
from app.errors import AppError
from app.routers import (
    auth as auth_router,
    backup,
    cash,
    deliveries,
    expenses,
    inventory,
    money,
    products,
    reconciliation,
    reports,
    sales,
    settings as settings_router,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("college_cart")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        accounts.ensure_schema()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Accounts database could not be initialized (%s).", exc)
    try:
        from app.database import SessionLocal
        from app.services.settings_service import ensure_defaults_installed

        db = SessionLocal()
        try:
            ensure_defaults_installed(db)
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Database is not initialized or could not be opened (%s). "
            "Run: .venv/Scripts/python -m app.bootstrap",
            exc,
        )
    yield


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description=(
        "Personal sales, inventory, cash and reconciliation manager for College Cart. "
        "The API is local-first; automatic integration with the public College Cart website "
        "is not available unless an authorized API is provided."
    ),
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

if settings.dev_cors:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def response_headers(request: Request, call_next):
    try:
        request.state.user = security.user_from_request(request)
    except Exception:  # noqa: BLE001
        logger.exception("Session lookup failed")
        request.state.user = None

    if request.method not in {"GET", "HEAD", "OPTIONS"} and request.url.path.startswith("/api/"):
        origin = request.headers.get("origin")
        host = request.headers.get("host", "")
        cross_site = request.headers.get("sec-fetch-site") == "cross-site"
        if (origin and urlsplit(origin).netloc != host) or cross_site:
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "cross_site_request",
                        "message": "Cross-site requests are not allowed.",
                        "details": None,
                    }
                },
            )

    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; "
        "manifest-src 'self'; worker-src 'self'; object-src 'none'; base-uri 'self'; "
        "form-action 'self'; frame-ancestors 'none'",
    )
    if request.url.scheme == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.url.path.startswith("/api"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content=jsonable_encoder(
            {
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            }
        ),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    first = errors[0] if errors else {}
    message = first.get("msg", "The request was invalid")
    location = ".".join(str(part) for part in first.get("loc", []) if part not in {"body", "query"})
    if location:
        message = f"{location}: {message}"
    return JSONResponse(
        status_code=422,
        content=jsonable_encoder(
            {
                "error": {
                    "code": "validation_error",
                    "message": message,
                    "details": errors,
                }
            }
        ),
    )


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    logger.warning("Database constraint violation: %s", exc)
    return JSONResponse(
        status_code=409,
        content={
            "error": {
                "code": "database_conflict",
                "message": "This record conflicts with existing data. Reload and check for duplicates.",
                "details": None,
            }
        },
    )


@app.exception_handler(OperationalError)
async def operational_error_handler(request: Request, exc: OperationalError):
    logger.error("Database unavailable: %s", exc)
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "database_unavailable",
                "message": "The database is not initialized. Run the documented bootstrap command.",
                "details": None,
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "Something went wrong while processing the request.",
                "details": None,
            }
        },
    )


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": __version__,
        "database": "sqlite" if settings.is_sqlite else "other",
        "timezone": settings.business_timezone,
        "accounts": accounts.accounts_exist(),
    }


for router in (
    auth_router.router,
    products.router,
    inventory.router,
    sales.router,
    expenses.router,
    money.router,
    cash.cash_router,
    cash.handover_router,
    cash.payment_router,
    deliveries.router,
    reconciliation.router,
    reports.router,
    settings_router.router,
    backup.router,
):
    app.include_router(router)


frontend = settings.frontend_dir
index_file = frontend / "index.html"
SHARE_IMAGE = "/social/college-cart-share.png"
SHARE_IMAGE_ALT = "College Cart Manager — sales, inventory, money and expense tracking"


def _public_base_url(request: Request) -> str:
    configured = settings.public_base_url.strip().rstrip("/")
    if configured:
        return configured
    return str(request.base_url).rstrip("/")


def _render_index(request: Request, path: str, status_code: int) -> HTMLResponse | JSONResponse | RedirectResponse:
    if not index_file.exists():
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "frontend_missing",
                    "message": "Frontend files are missing. The API is still available at /api/docs.",
                }
            },
        )

    user = getattr(request.state, "user", None)
    has_accounts = accounts.accounts_exist()
    if seo.is_app_path(path) and user is None and has_accounts:
        target = path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(f"/login?next={quote(target)}", status_code=303)

    base_url = _public_base_url(request)
    meta = seo.route_meta(path)
    known = meta is not None
    if meta is None:
        meta = {**seo.NOT_FOUND, "path": path}
    business_name = "College Cart"
    title = seo.document_title(meta)
    canonical = (
        f'<link rel="canonical" href="{html.escape(base_url + meta["path"], quote=True)}" id="canonical-link" />'
        if known
        else ""
    )
    robots = "noindex, nofollow"
    social_url = base_url + (meta["path"] if known else path)
    social_image = base_url + SHARE_IMAGE
    user_payload = {"id": user.id, "email": user.email} if user else None

    replacements = {
        "__CARTFLOW_TITLE__": html.escape(title),
        "__CARTFLOW_DESCRIPTION__": html.escape(meta["description"], quote=True),
        "__CARTFLOW_CANONICAL__": canonical,
        "__CARTFLOW_ROBOTS__": robots,
        "__CARTFLOW_OG_TITLE__": html.escape(title, quote=True),
        "__CARTFLOW_OG_DESCRIPTION__": html.escape(meta["description"], quote=True),
        "__CARTFLOW_OG_URL__": html.escape(social_url, quote=True),
        "__CARTFLOW_OG_IMAGE__": html.escape(social_image, quote=True),
        "__CARTFLOW_OG_IMAGE_ALT__": html.escape(SHARE_IMAGE_ALT, quote=True),
        "__CARTFLOW_HEADING__": html.escape(meta["title"]),
        "__CARTFLOW_SUBTITLE__": html.escape(meta["subtitle"]),
        "__CARTFLOW_BRAND__": html.escape(business_name),
        "__CARTFLOW_BUSINESS_LD__": seo.json_for_script(seo.local_business_json(base_url, business_name)),
        "__CARTFLOW_BREADCRUMB_LD__": seo.json_for_script(
            seo.breadcrumb_json(base_url, path) if known else None
        ),
        "__CARTFLOW_APP_META__": seo.json_for_script(
            seo.app_meta_payload(
                base_url,
                settings.allow_indexing,
                user=user_payload,
                allow_signup=settings.allow_signup or not has_accounts,
                has_accounts=has_accounts,
            )
        ),
    }
    text = index_file.read_text(encoding="utf-8")
    for token, value in replacements.items():
        text = text.replace(token, value)
    return HTMLResponse(text, status_code=status_code, headers={"Cache-Control": "no-store"})


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
def serve_root(request: Request):
    query = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(url=f"/dashboard{query}", status_code=308)


auth_file = frontend / "auth.html"


def _render_auth(request: Request, path: str) -> HTMLResponse | JSONResponse | RedirectResponse:
    meta = seo.auth_meta(path)
    if meta is None:
        return _render_index(request, path, 404)
    if getattr(request.state, "user", None) is not None:
        return RedirectResponse("/dashboard", status_code=303)
    if path == "/signup" and not settings.allow_signup and accounts.accounts_exist():
        return RedirectResponse("/login", status_code=303)
    if not auth_file.exists():
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "frontend_missing",
                    "message": "Frontend files are missing. The API is still available at /api/docs.",
                }
            },
        )

    base_url = _public_base_url(request)
    title = seo.document_title(meta)
    robots = "index, follow" if settings.allow_indexing else "noindex, nofollow"
    replacements = {
        "__CARTFLOW_TITLE__": html.escape(title),
        "__CARTFLOW_DESCRIPTION__": html.escape(meta["description"], quote=True),
        "__CARTFLOW_CANONICAL__": (
            f'<link rel="canonical" href="{html.escape(base_url + path, quote=True)}" id="canonical-link" />'
        ),
        "__CARTFLOW_ROBOTS__": robots,
        "__CARTFLOW_OG_TITLE__": html.escape(title, quote=True),
        "__CARTFLOW_OG_DESCRIPTION__": html.escape(meta["description"], quote=True),
        "__CARTFLOW_OG_URL__": html.escape(base_url + path, quote=True),
        "__CARTFLOW_OG_IMAGE__": html.escape(base_url + SHARE_IMAGE, quote=True),
        "__CARTFLOW_OG_IMAGE_ALT__": html.escape(SHARE_IMAGE_ALT, quote=True),
        "__CARTFLOW_HEADING__": html.escape(meta["heading"]),
        "__CARTFLOW_SUBTITLE__": html.escape(meta["subtitle"]),
        "__CARTFLOW_AUTH_MODE__": "signup" if path == "/signup" else "login",
        "__CARTFLOW_AUTH_ALT_HREF__": html.escape(meta["alt_path"], quote=True),
        "__CARTFLOW_AUTH_ALT_TEXT__": html.escape(meta["alt_text"]),
    }
    text = auth_file.read_text(encoding="utf-8")
    for token, value in replacements.items():
        text = text.replace(token, value)
    return HTMLResponse(text, status_code=200, headers={"Cache-Control": "no-store"})


@app.api_route("/login", methods=["GET", "HEAD"], include_in_schema=False)
def serve_login(request: Request):
    return _render_auth(request, "/login")


@app.api_route("/signup", methods=["GET", "HEAD"], include_in_schema=False)
def serve_signup(request: Request):
    return _render_auth(request, "/signup")


@app.api_route("/index.html", methods=["GET", "HEAD"], include_in_schema=False)
def serve_index_html(request: Request):
    return _render_index(request, "/dashboard", 200)


@app.get("/sw.js", include_in_schema=False)
def serve_service_worker():
    path = frontend / "sw.js"
    if not path.exists():
        return JSONResponse(status_code=404, content={"error": {"code": "not_found", "message": "sw.js missing"}})
    return FileResponse(
        path,
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


@app.get("/manifest.webmanifest", include_in_schema=False)
def serve_manifest():
    path = frontend / "manifest.webmanifest"
    if not path.exists():
        return JSONResponse(status_code=404, content={"error": {"code": "not_found", "message": "Manifest missing"}})
    return FileResponse(
        path,
        media_type="application/manifest+json",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/sitemap.xml", include_in_schema=False)
def serve_sitemap(request: Request):
    return PlainTextResponse(
        seo.sitemap_xml(_public_base_url(request)),
        media_type="application/xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/robots.txt", include_in_schema=False)
def serve_robots(request: Request):
    return PlainTextResponse(
        seo.robots_txt(_public_base_url(request), settings.allow_indexing),
        media_type="text/plain",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.api_route("/robot.txt", methods=["GET", "HEAD"], include_in_schema=False)
def serve_robot_alias():
    return RedirectResponse("/robots.txt", status_code=308)


@app.get("/llms.txt", include_in_schema=False)
def serve_llms(request: Request):
    return PlainTextResponse(
        seo.llms_txt(_public_base_url(request)),
        media_type="text/plain",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/favicon.ico", include_in_schema=False)
def serve_favicon():
    path = frontend / "favicon.ico"
    if not path.exists():
        return JSONResponse(status_code=404, content={"error": {"code": "not_found", "message": "Favicon missing"}})
    return FileResponse(
        path,
        media_type="image/x-icon",
        headers={"Cache-Control": "public, max-age=604800"},
    )


for asset_dir in ("css", "js", "icons", "social"):
    directory = frontend / asset_dir
    if directory.exists():
        app.mount(f"/{asset_dir}", StaticFiles(directory=str(directory)), name=f"frontend-{asset_dir}")


@app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
def serve_app(full_path: str, request: Request):
    path = f"/{full_path}" if full_path else "/"
    if path == "/api" or path.startswith("/api/"):
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "not_found",
                    "message": "The requested API endpoint does not exist.",
                    "details": None,
                }
            },
        )
    if Path(full_path).suffix:
        return PlainTextResponse("Not found", status_code=404)
    normalized = seo.normalize_path(path)
    if normalized != path and (seo.is_app_path(normalized) or seo.is_auth_path(normalized)):
        return RedirectResponse(normalized, status_code=308)
    if seo.is_auth_path(normalized):
        return _render_auth(request, normalized)
    status_code = 200 if seo.is_app_path(path) else 404
    return _render_index(request, path, status_code)
