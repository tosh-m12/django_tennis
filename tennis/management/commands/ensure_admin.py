import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import OperationalError, ProgrammingError, connection

class Command(BaseCommand):
    help = "Create or reset a superuser from env vars."

    def handle(self, *args, **options):
        username = os.environ.get("ADMIN_RESET_USERNAME")
        password = os.environ.get("ADMIN_RESET_PASSWORD")
        email = os.environ.get("ADMIN_RESET_EMAIL", "")

        if not username or not password:
            self.stdout.write(self.style.WARNING("ADMIN_RESET_USERNAME / ADMIN_RESET_PASSWORD is required"))
            return

        # DB/テーブル未準備なら落とさず終了
        try:
            with connection.cursor() as cur:
                cur.execute("SELECT 1")
        except (OperationalError, ProgrammingError) as e:
            self.stdout.write(self.style.WARNING(f"DB not ready: {e}"))
            return

        User = get_user_model()

        try:
            user = User.objects.filter(username=username).first()
        except (OperationalError, ProgrammingError) as e:
            self.stdout.write(self.style.WARNING(f"Auth table not ready: {e}"))
            return

        if user is None:
            user = User.objects.create_superuser(username=username, email=email, password=password)
            self.stdout.write(self.style.SUCCESS(f"superuser created: {username}"))
        else:
            user.set_password(password)
            user.is_staff = True
            user.is_superuser = True
            user.save()
            self.stdout.write(self.style.SUCCESS(f"superuser password reset: {username}"))
