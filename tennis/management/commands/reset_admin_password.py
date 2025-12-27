import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    help = "Create or update admin user from env vars"

    def handle(self, *args, **options):
        username = (os.environ.get("ADMIN_RESET_USERNAME") or "").strip()
        password = (os.environ.get("ADMIN_RESET_PASSWORD") or "").strip()
        email = (os.environ.get("ADMIN_RESET_EMAIL") or "").strip()  # optional

        if not username or not password:
            raise SystemExit("ADMIN_RESET_USERNAME / ADMIN_RESET_PASSWORD is required")

        User = get_user_model()

        defaults = {}
        if email:
            defaults["email"] = email

        u, created = User.objects.get_or_create(username=username, defaults=defaults)
        u.set_password(password)
        u.is_staff = True
        u.is_superuser = True
        if email and hasattr(u, "email"):
            u.email = email
        u.save()

        self.stdout.write("admin created" if created else "admin updated")
