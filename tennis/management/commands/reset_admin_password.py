import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    help = "Reset admin password from env vars"

    def handle(self, *args, **options):
        username = os.environ.get("ADMIN_RESET_USERNAME", "").strip()
        password = os.environ.get("ADMIN_RESET_PASSWORD", "").strip()

        if not username or not password:
            raise SystemExit("ADMIN_RESET_USERNAME / ADMIN_RESET_PASSWORD is required")

        User = get_user_model()
        try:
            u = User.objects.get(username=username)
        except User.DoesNotExist:
            raise SystemExit(f"user not found: {username}")

        u.set_password(password)
        u.is_staff = True
        u.is_superuser = True
        u.save()
        self.stdout.write("admin password reset OK")
