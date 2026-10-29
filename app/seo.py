from __future__ import annotations

import json
import re
from datetime import date

APP_NAME = "College Cart Manager"
APP_DESCRIPTION = (
    "Personal sales, inventory, cash and reconciliation manager for a student snack "
    "and delivery business."
)

SALE_DETAIL_PATTERN = re.compile(r"^/sales/(?P<sale_id>\d+)$")

ROUTES: dict[str, dict[str, str]] = {
    "/dashboard": {
        "title": "Dashboard",
        "subtitle": "Sales, money, expenses and cash at a glance.",
        "description": (
            "Daily sales, money received, expenses, cash and UPI balances, pending payments "
            "and low-stock alerts for your College Cart business."
        ),
        "nav": "dashboard",
    },
    "/new-sale": {
        "title": "New Sale",
        "subtitle": "Record a walk-in, website or phone order — works offline.",
        "description": (
            "Record a walk-in, website or phone order, take a payment and keep stock in sync, "
            "even while the server is offline."
        ),
        "nav": "new-sale",
    },
    "/sales": {
        "title": "Sales History",
        "subtitle": "Every sale with its products, payments, delivery and sync status.",
        "description": (
            "Search, filter and review every sale, payment status, return and delivery for "
            "your College Cart business."
        ),
        "nav": "sales",
    },
    "/inventory": {
        "title": "Inventory",
        "subtitle": "Products, stock levels, receipts and every movement.",
        "description": (
            "Manage products, stock levels, low-stock alerts, stock receipts, purchases and "
            "every inventory movement."
        ),
        "nav": "inventory",
    },
    "/expenses": {
        "title": "Expenses",
        "subtitle": "Ordinary operating costs and stock purchases, kept separate in Money History.",
        "description": (
            "Record ordinary business costs and stock purchases with clear categories and an "
            "auditable history."
        ),
        "nav": "expenses",
    },
    "/money-history": {
        "title": "Money History",
        "subtitle": "A permanent ledger of money received and given, including sale payments, expenses and owner handovers.",
        "description": (
            "A permanent ledger of money received and given, including sale payments, expenses, "
            "owner handovers and cash/UPI transfers."
        ),
        "nav": "money-history",
    },
    "/reports": {
        "title": "Reports",
        "subtitle": "Sales, money movement, expenses and stock without accounting jargon.",
        "description": (
            "Daily and monthly sales, money movement, expense and stock reports without "
            "accounting jargon."
        ),
        "nav": "reports",
    },
    "/settings": {
        "title": "Settings & Backup",
        "subtitle": "Business preferences, money categories, opening balances, backups and offline queue.",
        "description": (
            "Change business details, opening balances, categories and payment methods, then "
            "manage backups and the offline queue."
        ),
        "nav": "settings",
    },
}

NOT_FOUND = {
    "title": "Page not found",
    "subtitle": "That address does not match any page in this app.",
    "description": "The page you requested does not exist. Use the links to return to College Cart Manager.",
    "nav": "",
}

AUTH_ROUTES: dict[str, dict[str, str]] = {
    "/login": {
        "title": "Sign in",
        "heading": "Sign in",
        "subtitle": "Use the email and password for your College Cart account.",
        "description": (
            "Sign in to College Cart Manager to open your own sales, inventory, money and "
            "expense records."
        ),
        "alt_path": "/signup",
        "alt_text": "New here? Create an account",
    },
    "/signup": {
        "title": "Create account",
        "heading": "Create your account",
        "subtitle": "Your products, sales, money and backups stay separate from every other account.",
        "description": (
            "Create a private College Cart Manager account. The first account keeps the existing "
            "records on this server; every later account starts with its own empty workspace."
        ),
        "alt_path": "/login",
        "alt_text": "Already have an account? Sign in",
    },
}

SITEMAP_ROUTES = tuple(AUTH_ROUTES)
SITEMAP_PRIORITIES = {"/login": "0.6", "/signup": "0.5"}


def normalize_path(path: str) -> str:
    if not path or path == "/":
        return "/dashboard"
    if len(path) > 1 and path.endswith("/"):
        return path.rstrip("/")
    return path


def route_meta(path: str) -> dict[str, str] | None:
    normalized = normalize_path(path)
    sale = SALE_DETAIL_PATTERN.match(normalized)
    if sale:
        sale_id = sale.group("sale_id")
        return {
            "path": normalized,
            "title": f"Sale #{sale_id}",
            "subtitle": "Items, payments, returns and audit history for one sale.",
            "description": (
                f"Items, payments, returns, delivery and audit history for sale #{sale_id} "
                "in College Cart Manager."
            ),
            "nav": "sales",
        }
    page = ROUTES.get(normalized)
    if not page:
        return None
    return {"path": normalized, **page}


def is_app_path(path: str) -> bool:
    return route_meta(path) is not None


def auth_meta(path: str) -> dict[str, str] | None:
    normalized = normalize_path(path)
    page = AUTH_ROUTES.get(normalized)
    if not page:
        return None
    return {"path": normalized, **page}


def is_auth_path(path: str) -> bool:
    return auth_meta(path) is not None


def canonical_path(path: str) -> str:
    meta = route_meta(path)
    if not meta:
        return "/dashboard"
    return meta["path"]


def document_title(meta: dict[str, str]) -> str:
    return f"{meta['title']} · {APP_NAME}"


def breadcrumbs(path: str) -> list[dict[str, str]]:
    meta = route_meta(path)
    if not meta:
        return [{"name": "Dashboard", "path": "/dashboard"}]
    items = [{"name": "Dashboard", "path": "/dashboard"}]
    if meta["nav"] == "sales":
        items.append({"name": "Sales History", "path": "/sales"})
    if meta["nav"] not in {"", "dashboard", "sales"}:
        items.append({"name": meta["title"], "path": meta["path"]})
    elif meta["nav"] == "sales" and meta["path"] != "/sales":
        items.append({"name": meta["title"], "path": meta["path"]})
    return items


def app_meta_payload(
    base_url: str,
    allow_indexing: bool,
    *,
    user: dict | None = None,
    allow_signup: bool = True,
    has_accounts: bool = False,
) -> dict:
    return {
        "appName": APP_NAME,
        "baseUrl": base_url,
        "allowIndexing": allow_indexing,
        "authenticated": user is not None,
        "user": user,
        "allowSignup": allow_signup,
        "hasAccounts": has_accounts,
        "routes": ROUTES,
        "notFound": NOT_FOUND,
    }


def json_for_script(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace("</", "<\\/")


def local_business_json(base_url: str, business_name: str) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "@id": f"{base_url}/#business",
        "name": business_name,
        "description": APP_DESCRIPTION,
        "url": f"{base_url}/",
        "logo": f"{base_url}/icons/app-icon.svg",
        "image": f"{base_url}/social/college-cart-share.png",
        "areaServed": "College campus",
        "currenciesAccepted": "INR",
        "paymentAccepted": "Cash, UPI",
    }


def breadcrumb_json(base_url: str, path: str) -> dict:
    items = breadcrumbs(path)
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": index,
                "name": item["name"],
                "item": f"{base_url}{item['path']}",
            }
            for index, item in enumerate(items, start=1)
        ],
    }


def sitemap_xml(base_url: str) -> str:
    today = date.today().isoformat()
    entries = []
    for path in SITEMAP_ROUTES:
        entries.append(
            "  <url>"
            f"<loc>{base_url}{path}</loc>"
            f"<lastmod>{today}</lastmod>"
            "<changefreq>weekly</changefreq>"
            f"<priority>{SITEMAP_PRIORITIES[path]}</priority>"
            "</url>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(entries)
        + "\n</urlset>\n"
    )


def robots_txt(base_url: str, allow_indexing: bool) -> str:
    if not allow_indexing:
        return (
            "# College Cart Manager holds private business and financial records.\n"
            "# Public indexing is disabled while the server holds private account data.\n"
            "# Set CARTFLOW_ALLOW_INDEXING=true only to publish the sign-in pages.\n"
            "User-agent: *\n"
            "Disallow: /\n"
        )
    lines = [
        "User-agent: *",
        "Allow: /login",
        "Allow: /signup",
        "Disallow: /api/",
    ]
    lines.extend(f"Disallow: {path}" for path in ROUTES)
    lines.extend(["", f"Sitemap: {base_url}/sitemap.xml", ""])
    return "\n".join(lines)


def llms_txt(base_url: str) -> str:
    lines = [
        f"# {APP_NAME}",
        "",
        f"> {APP_DESCRIPTION}",
        "",
        "College Cart Manager is a local-first, multi-account business tracker with sales, "
        "inventory, expenses, a money ledger, reports, offline entry and safe backups.",
        "",
        "## Sign-in pages",
    ]
    for path, page in AUTH_ROUTES.items():
        lines.append(f"- [{page['heading']}]({base_url}{path}): {page['description']}")
    lines.extend(
        [
            "",
            "## Notes",
            "- Every account has a separate database; signed-in pages are private.",
            "- The application does not publish customer, sales or payment data.",
            "- Automatic import from an external College Cart website is not available.",
            "",
        ]
    )
    return "\n".join(lines)
