import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    help = "Create or reset a superuser from env vars."

    def handle(self, *args, **options):
        username = os.environ.get("ADMIN_RESET_USERNAME")
        password = os.environ.get("ADMIN_RESET_PASSWORD")
        email = os.environ.get("ADMIN_RESET_EMAIL", "")  # 任意

        if not username or not password:
            self.stdout.write(self.style.WARNING("ADMIN_RESET_USERNAME / ADMIN_RESET_PASSWORD is required"))
            return

        User = get_user_model()

        user = User.objects.filter(username=username).first()
        if user is None:
            user = User.objects.create_superuser(username=username, email=email, password=password)
            self.stdout.write(self.style.SUCCESS(f"superuser created: {username}"))
        else:
            user.set_password(password)
            user.is_staff = True
            user.is_superuser = True
            user.save()
            self.stdout.write(self.style.SUCCESS(f"superuser password reset: {username}"))
