from __future__ import annotations

import json
import re
import struct
from pathlib import Path

from app.config import settings

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

PUBLIC_ROUTES = (
    "/dashboard",
    "/new-sale",
    "/sales",
    "/inventory",
    "/expenses",
    "/money-history",
    "/reports",
    "/settings",
)


def title_of(html: str) -> str:
    match = re.search(r"<title>(.*?)</title>", html, re.S)
    assert match, "missing <title>"
    return match.group(1).strip()


def description_of(html: str) -> str:
    match = re.search(r'<meta name="description" content="(.*?)" />', html, re.S)
    assert match, "missing meta description"
    return match.group(1).strip()


def jsonld_of(html: str, element_id: str):
    match = re.search(
        rf'<script type="application/ld\+json" id="{element_id}">(.*?)</script>',
        html,
        re.S,
    )
    assert match, f"missing JSON-LD {element_id}"
    return json.loads(match.group(1))


def test_root_redirects_to_dashboard(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 308
    assert response.headers["location"] == "/dashboard"


def test_every_page_has_unique_title_description_and_canonical(client, monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://cart.example.com")
    monkeypatch.setattr(settings, "allow_indexing", False)

    titles: set[str] = set()
    descriptions: set[str] = set()
    for path in PUBLIC_ROUTES:
        response = client.get(path)
        assert response.status_code == 200, path
        html = response.text
        assert html.count("<h1") == 1, f"{path} must have exactly one h1"
        title = title_of(html)
        description = description_of(html)
        assert title not in titles, f"duplicate title for {path}"
        assert description not in descriptions, f"duplicate description for {path}"
        titles.add(title)
        descriptions.add(description)
        assert title.endswith("· College Cart Manager")
        assert f'<link rel="canonical" href="https://cart.example.com{path}" id="canonical-link" />' in html
        assert '<meta name="robots" content="noindex, nofollow" />' in html
        assert "__CARTFLOW_" not in html


def test_sale_detail_deep_link_has_dynamic_metadata_and_breadcrumbs(client, monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://cart.example.com")
    response = client.get("/sales/42")
    assert response.status_code == 200
    html = response.text
    assert "<title>Sale #42 · College Cart Manager</title>" in html
    assert '<link rel="canonical" href="https://cart.example.com/sales/42" id="canonical-link" />' in html
    assert '<h1 id="page-title">Sale #42</h1>' in html

    schema = jsonld_of(html, "breadcrumb-jsonld")
    assert schema["@type"] == "BreadcrumbList"
    names = [item["name"] for item in schema["itemListElement"]]
    assert names == ["Dashboard", "Sales History", "Sale #42"]
    assert schema["itemListElement"][1]["item"] == "https://cart.example.com/sales"


def test_structured_data_identifies_the_business(client, monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://cart.example.com")
    html = client.get("/dashboard").text
    schema = jsonld_of(html, "local-business-jsonld")
    assert schema["@type"] == "LocalBusiness"
    assert schema["name"] == "College Cart"
    assert schema["url"] == "https://cart.example.com/"
    assert schema["image"] == "https://cart.example.com/social/college-cart-share.png"
    assert schema["currenciesAccepted"] == "INR"

    breadcrumbs = jsonld_of(html, "breadcrumb-jsonld")
    assert [item["name"] for item in breadcrumbs["itemListElement"]] == ["Dashboard"]


def test_unknown_page_returns_custom_404(client):
    response = client.get("/this-page-does-not-exist")
    assert response.status_code == 404
    html = response.text
    assert "<title>Page not found · College Cart Manager</title>" in html
    assert '<meta name="robots" content="noindex, nofollow" />' in html
    assert 'id="canonical-link"' not in html
    assert html.count("<h1") == 1
    assert '<h1 id="page-title">Page not found</h1>' in html
    assert 'href="/dashboard"' in html

    sale = client.get("/sales/not-a-number")
    assert sale.status_code == 404


def test_unknown_api_path_stays_json(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "not_found"


def test_sitemap_robots_and_llms_are_published(client, monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://cart.example.com")
    monkeypatch.setattr(settings, "allow_indexing", False)

    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200
    assert sitemap.headers["content-type"].startswith("application/xml")
    for path in ("/login", "/signup"):
        assert f"<loc>https://cart.example.com{path}</loc>" in sitemap.text
    for path in PUBLIC_ROUTES:
        assert f"<loc>https://cart.example.com{path}</loc>" not in sitemap.text

    robots = client.get("/robots.txt")
    assert robots.status_code == 200
    assert "Disallow: /" in robots.text
    assert "Allow: /login" not in robots.text

    alias = client.get("/robot.txt", follow_redirects=False)
    assert alias.status_code == 308
    assert alias.headers["location"] == "/robots.txt"

    llms = client.get("/llms.txt")
    assert llms.status_code == 200
    assert llms.text.startswith("# College Cart Manager")
    assert "https://cart.example.com/login" in llms.text
    assert "https://cart.example.com/signup" in llms.text


def test_indexing_can_be_enabled_for_a_public_deployment(client, monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "https://cart.example.com/")
    monkeypatch.setattr(settings, "allow_indexing", True)

    robots = client.get("/robots.txt")
    assert "Allow: /login" in robots.text
    assert "Allow: /signup" in robots.text
    assert "Disallow: /dashboard" in robots.text
    assert "Sitemap: https://cart.example.com/sitemap.xml" in robots.text

    html = client.get("/reports").text
    assert '<meta name="robots" content="noindex, nofollow" />' in html

    login = client.get("/login").text
    assert '<meta name="robots" content="index, follow" />' in login
    assert '<link rel="canonical" href="https://cart.example.com/login" id="canonical-link" />' in login


def test_favicon_social_image_and_app_icons_are_served(client):
    favicon = client.get("/favicon.ico")
    assert favicon.status_code == 200
    assert favicon.headers["content-type"].startswith("image/x-icon")

    for path in ("/icons/icon-192.png", "/icons/icon-512.png", "/icons/apple-touch-icon.png"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers["content-type"].startswith("image/png")

    share = client.get("/social/college-cart-share.png")
    assert share.status_code == 200
    assert share.headers["content-type"].startswith("image/png")
    width, height = struct.unpack(">II", share.content[16:24])
    assert (width, height) == (1200, 630)


def test_shell_uses_crawlable_internal_links_and_no_placeholder_branding(client):
    html = client.get("/dashboard").text
    for path in PUBLIC_ROUTES:
        assert f'href="{path}"' in html, f"missing internal link to {path}"
    assert 'href="#/' not in html
    assert "vite" not in html.lower()
    assert re.search(r"\breact\b", html.lower()) is None


def test_frontend_has_no_source_maps_or_placeholder_framework_text():
    assert not list(FRONTEND.rglob("*.map"))
    for path in FRONTEND.rglob("*"):
        if path.suffix not in {".js", ".html", ".webmanifest"}:
            continue
        text = path.read_text(encoding="utf-8").lower()
        assert "vite" not in text, f"Vite reference in {path}"
        assert re.search(r"\breact\b", text) is None, f"React reference in {path}"


def test_router_supports_history_navigation_and_a_not_found_page():
    router = (FRONTEND / "js" / "router.js").read_text(encoding="utf-8")
    assert "pushState" in router
    assert "popstate" in router
    assert "not-found" in router
    assert "canonical" in router
    assert (FRONTEND / "js" / "pages" / "not-found.js").exists()
