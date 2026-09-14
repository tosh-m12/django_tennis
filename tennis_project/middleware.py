"""プロジェクト共通ミドルウェア。"""
import logging

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured, MiddlewareNotUsed
from django.http import JsonResponse, HttpResponse, HttpResponsePermanentRedirect
from django.utils import timezone
from django.utils.crypto import constant_time_compare

from tennis.models import Club
from tennis.security import rate_limit_exceeded


log = logging.getLogger(__name__)


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


class ClubAccessMiddleware:
    """クラブ画面への最終アクセスを、同じURLごと5分に1回まで記録する。"""

    WRITE_INTERVAL_SECONDS = 300

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if response.status_code >= 400:
            return response

        match = getattr(request, "resolver_match", None)
        kwargs = getattr(match, "kwargs", {}) or {}
        club_path_token = kwargs.get("club_public_token")
        if not club_path_token:
            return response

        admin_token = kwargs.get("club_admin_token")
        access_kind = "admin" if admin_token else "public"
        cache_key = f"club-last-access:{access_kind}:{club_path_token}"

        try:
            if not cache.add(cache_key, True, timeout=self.WRITE_INTERVAL_SECONDS):
                return response

            lookup = {"is_active": True}
            if admin_token:
                lookup.update(
                    admin_path_token=club_path_token,
                    admin_token=admin_token,
                )
            else:
                lookup["public_token"] = club_path_token

            updated = Club.objects.filter(**lookup).update(last_accessed_at=timezone.now())
            if not updated:
                cache.delete(cache_key)
        except Exception:
            # 記録の失敗で利用者の画面表示を止めない。
            log.exception("Failed to record club access")

        return response


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
