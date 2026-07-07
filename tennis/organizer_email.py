"""
幹事メール（ClubOrganizer）まわりの共通処理。
- 確認トークン（Django signing・追加テーブル不要）
- 確認メール／復旧メールの送信
- 送信レート制限（EmailThrottle・DB記録型）

送信元は settings.DEFAULT_FROM_EMAIL（no-reply@deucenet.app）。
RESEND_API_KEY 未設定時はコンソールバックエンドに流れる（settings 参照）。
"""

from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone

from .models import EmailThrottle

CONFIRM_SALT = "tennis.organizer.confirm"
CONFIRM_MAX_AGE = 60 * 60 * 48  # 確認リンクの有効期限：48時間


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


# ------------------------------------------------------------
# 確認トークン
# ------------------------------------------------------------

def make_confirm_token(organizer_id: int, email: str) -> str:
    return signing.dumps({"oid": organizer_id, "email": email}, salt=CONFIRM_SALT)


def read_confirm_token(token: str):
    """成功: (data_dict, None) / 失敗: (None, 'expired'|'invalid')。"""
    try:
        data = signing.loads(token, salt=CONFIRM_SALT, max_age=CONFIRM_MAX_AGE)
    except signing.SignatureExpired:
        return None, "expired"
    except (signing.BadSignature, Exception):
        return None, "invalid"
    return data, None


# ------------------------------------------------------------
# 絶対URL
# ------------------------------------------------------------

def _abs(request, name, args):
    return request.build_absolute_uri(reverse(name, args=args))


# ------------------------------------------------------------
# メール送信
# ------------------------------------------------------------

def send_confirmation_email(request, organizer) -> None:
    """幹事メール登録の確認メール。organizer.email 宛に確認リンクを送る。"""
    token = make_confirm_token(organizer.id, organizer.email)
    url = _abs(request, "tennis:verify_email", [token])
    club_name = organizer.club.name
    subject = f"[Deucenet] メールアドレスの確認（{club_name}）"
    body = (
        f"{club_name} の幹事メール登録の確認です。\n\n"
        f"下のリンクを開くと登録が完了します（48時間以内）:\n{url}\n\n"
        f"心当たりがない場合は、このメールを破棄してください。\n"
    )
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [organizer.email], fail_silently=False)


def send_recovery_email(request, email: str, organizers) -> None:
    """確認済み ClubOrganizer 群に対応するクラブURLを、その登録アドレスに再送。"""
    blocks = []
    for org in organizers:
        club = org.club
        admin_url = _abs(request, "tennis:club_home_admin", [club.public_token, club.admin_token])
        public_url = _abs(request, "tennis:club_home", [club.public_token])
        blocks.append(
            f"■ {club.name}\n"
            f"  幹事用URL（あなた専用・共有しないでください）:\n  {admin_url}\n\n"
            f"  メンバー用URL（メンバーに配ってOK）:\n  {public_url}\n"
        )
    body = (
        "Deucenet のクラブURL再送です。\n\n"
        + "\n".join(blocks)
        + "\n心当たりがない場合は、このメールを破棄してください。\n"
    )
    subject = "[Deucenet] クラブURLの再送"
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [email], fail_silently=False)


# ------------------------------------------------------------
# レート制限
# ------------------------------------------------------------

def throttle_ok(scope: str, key: str, limit: int, window_seconds: int) -> bool:
    """
    直近 window_seconds 内の (scope,key) の試行が limit 未満なら True を返し、1件記録する。
    limit 以上なら False（＝送信させない）。key が空なら素通し。
    """
    if not key:
        return True
    since = timezone.now() - timedelta(seconds=window_seconds)
    recent = EmailThrottle.objects.filter(scope=scope, key=key, created_at__gte=since).count()
    if recent >= limit:
        return False
    EmailThrottle.objects.create(scope=scope, key=key)
    return True
