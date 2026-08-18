"""プロジェクト共通ミドルウェア。"""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, MiddlewareNotUsed
from django.http import JsonResponse, HttpResponse, HttpResponsePermanentRedirect
from django.utils.crypto import constant_time_compare

from tennis.security import rate_limit_exceeded


class OriginVerifyMiddleware:
    """Cloudflareが付与する秘密ヘッダーを検証し、Railway直アクセスを拒否する。"""

    def __init__(self, get_response):
        self.get_response = get_response
        if not getattr(settings, "ORIGIN_VERIFY_ENABLED", False):
            raise MiddlewareNotUsed()
        self.secret = (getattr(settings, "ORIGIN_VERIFY_SECRET", "") or "").strip()
        if not self.secret:
            raise ImproperlyConfigured(
                "ORIGIN_VERIFY_ENABLED requires ORIGIN_VERIFY_SECRET"
            )

    def __call__(self, request):
        if request.path == "/healthz":
            return self.get_response(request)

        supplied = (request.META.get("HTTP_X_ORIGIN_VERIFY") or "").strip()
        if not supplied or not constant_time_compare(supplied, self.secret):
            return HttpResponse("Forbidden", status=403, content_type="text/plain")

        request.origin_verified = True
        return self.get_response(request)


class CanonicalHostRedirectMiddleware:
    """
    旧ホスト（例: *.up.railway.app）へのアクセスを正規ホスト（deucenet.app）へ 301 する。

    Cloudflare は正規ドメインしか経由しない（旧 railway ドメインは Cloudflare を通らない）ため、
    リダイレクトはアプリ側で行う。settings.CANONICAL_HOST が空なら無効（dev では何もしない）。
    Railway のヘルスチェックホスト(healthcheck.railway.app)は REDIRECT_HOSTS に含めないので影響なし。
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.canonical = (getattr(settings, "CANONICAL_HOST", "") or "").strip()
        self.redirect_hosts = {h for h in getattr(settings, "REDIRECT_HOSTS", []) if h}
        if not self.canonical or not self.redirect_hosts:
            raise MiddlewareNotUsed()  # 未設定なら完全に無効化（オーバーヘッドゼロ）

    def __call__(self, request):
        host = request.get_host().split(":")[0]
        if host in self.redirect_hosts and host != self.canonical:
            return HttpResponsePermanentRedirect(
                f"https://{self.canonical}{request.get_full_path()}"
            )
        return self.get_response(request)


class WriteRateLimitMiddleware:
    """公開更新APIをセッション/IP単位で抑制する。"""

    WRITE_PREFIXES = ("/api/", "/ajax/", "/clubs/", "/club/")

    def __init__(self, get_response):
        self.get_response = get_response
        if not getattr(settings, "APP_RATE_LIMIT_ENABLED", False):
            raise MiddlewareNotUsed()
        self.limit = int(getattr(settings, "WRITE_RATE_LIMIT", 120))
        self.window = int(getattr(settings, "WRITE_RATE_WINDOW_SECONDS", 60))

    def __call__(self, request):
        if request.method == "POST" and request.path.startswith(self.WRITE_PREFIXES):
            if rate_limit_exceeded(
                request,
                scope="write",
                limit=self.limit,
                window_seconds=self.window,
            ):
                response = JsonResponse(
                    {"ok": False, "error": "rate_limited"}, status=429
                )
                response["Retry-After"] = str(self.window)
                return response
        return self.get_response(request)
