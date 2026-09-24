"""Allowlisted GA4 funnel events. Never send club URLs or user-entered text."""
import re
from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_GET

from .seo import PUBLIC_PAGES

QUEUE = "analytics_events"


def enabled(request):
    return bool(settings.GA4_MEASUREMENT_ID and request.get_host().split(":")[0] in settings.GA4_HOSTS)


def client_id(request):
    match = re.fullmatch(r"GA\d+\.\d+\.(\d{1,20}\.\d{1,20})", request.COOKIES.get("_ga", ""))
    return match.group(1) if match else ""


def queue(request, name, *, mode="", cid=""):
    if not enabled(request):
        return
    event = {"name": name}
    if mode in ("member", "admin"):
        event["mode"] = mode
    if re.fullmatch(r"\d{1,20}\.\d{1,20}", cid):
        event["client_id"] = cid
    request.session[QUEUE] = (request.session.get(QUEUE, []) + [event])[-10:]


def context(request):
    if not enabled(request):
        return {}
    name = getattr(getattr(request, "resolver_match", None), "view_name", "")
    public = name in PUBLIC_PAGES
    events = request.session.pop(QUEUE, [])
    # No third-party scripts run in the actual application document.
    if not public and not events:
        return {}
    referrer = ""
    try:
        host = (urlsplit(request.META.get("HTTP_REFERER", "")).hostname or "").lower()
        # Explicit categories, rather than transmitting arbitrary referrer URLs.
        for domain in ("google.com", "google.co.jp", "bing.com", "yahoo.co.jp", "chatgpt.com", "perplexity.ai", "t.co", "x.com"):
            if host == domain or host.endswith("." + domain):
                referrer = "https://" + domain + "/"
                break
    except ValueError:
        pass
    return {"analytics_config": {
        "page": request.path if public else "",
        "referrer": referrer,
        "events": events,
    }}


@require_GET
@never_cache
@xframe_options_sameorigin
def frame(request):
    if not enabled(request):
        return HttpResponse(status=204)
    response = render(request, "tennis/analytics_frame.html", {"measurement_id": settings.GA4_MEASUREMENT_ID})
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response
