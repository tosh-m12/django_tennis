"""
Resend/メール送信の疎通確認用コマンド。

使い方:
    python manage.py send_test_email you@example.com

- RESEND_API_KEY が設定されていれば Resend 経由で実送信。
- 未設定ならコンソールバックエンドで内容を標準出力に表示（送信はしない）。
- 送信元は settings.DEFAULT_FROM_EMAIL（既定 no-reply@deucenet.app）。
"""

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "指定アドレスにテストメールを1通送り、メール基盤の疎通を確認する"

    def add_arguments(self, parser):
        parser.add_argument("to", help="送信先メールアドレス")

    def handle(self, *args, **options):
        to = options["to"].strip()
        if "@" not in to:
            raise CommandError(f"送信先が不正です: {to!r}")

        backend = settings.EMAIL_BACKEND
        keyed = bool(getattr(settings, "RESEND_API_KEY", ""))
        self.stdout.write(f"backend = {backend}")
        self.stdout.write(f"from    = {settings.DEFAULT_FROM_EMAIL}")
        self.stdout.write(f"to      = {to}")
        if not keyed:
            self.stdout.write(self.style.WARNING(
                "RESEND_API_KEY 未設定 → コンソール出力にフォールバック（実送信なし）"
            ))

        sent = send_mail(
            subject="[Deucenet] メール送信テスト",
            message="これは Deucenet のメール基盤（Resend）疎通確認メールです。\n"
                    "このメールが届いていれば設定は正常です。",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[to],
            fail_silently=False,
        )

        if sent:
            self.stdout.write(self.style.SUCCESS(f"送信処理 OK（{sent}件）"))
        else:
            raise CommandError("送信に失敗しました（sent=0）")
