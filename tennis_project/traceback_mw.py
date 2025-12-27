# tennis_project/traceback_mw.py
import traceback
from django.http import HttpResponse

class TracebackLoggingMiddleware:
    """
    本番で 500 の原因を確実にログへ出すための一時ミドルウェア。
    例外を握りつぶさず、stdout に traceback を出した上で 500 を返す。
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            return self.get_response(request)
        except Exception:
            traceback.print_exc()
            return HttpResponse("Server Error (traceback logged)", status=500)
