"""Search metadata for explicitly public pages; never enumerate club URLs."""
from xml.sax.saxutils import escape

from django.http import HttpResponse
from django.urls import reverse
from django.views.decorators.http import require_safe


PUBLIC_ORIGIN = "https://deucenet.app"
PUBLIC_PAGES = ("tennis:index", "tennis:privacy", "tennis:terms", "tennis:guide")


def is_public_page(request):
    match = getattr(request, "resolver_match", None)
    return request.method in ("GET", "HEAD") and getattr(match, "view_name", None) in PUBLIC_PAGES


def metadata(request):
    if not is_public_page(request):
        return {}
    name = request.resolver_match.view_name
    return {
        "seo_canonical": PUBLIC_ORIGIN + reverse(name),
        "seo_is_home": name == "tennis:index",
    }


@require_safe
def robots(request):
    # /c/ is crawlable so crawlers can observe its noindex response header.
    # robots.txt and noindex are not access controls for token-based URLs.
    body = "\n".join([
        "User-agent: *",
        "Disallow: /admin/",
        "Disallow: /api/",
        "Disallow: /ajax/",
        "Disallow: /club/",
        "Disallow: /clubs/",
        "Disallow: /verify/",
        "Disallow: /registration/",
        "Disallow: /recover/",
        "Disallow: /demo",
        "",
        f"Sitemap: {PUBLIC_ORIGIN}/sitemap.xml",
        "",
    ])
    return HttpResponse(body, content_type="text/plain; charset=utf-8")


@require_safe
def sitemap(request):
    urls = "".join(
        f"<url><loc>{escape(PUBLIC_ORIGIN + reverse(name))}</loc></url>"
        for name in PUBLIC_PAGES
    )
    return HttpResponse(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + urls + "</urlset>",
        content_type="application/xml; charset=utf-8",
    )
