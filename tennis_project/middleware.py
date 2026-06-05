"""プロジェクト共通ミドルウェア。"""
from django.conf import settings
from django.core.exceptions import MiddlewareNotUsed
from django.http import HttpResponsePermanentRedirect


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
