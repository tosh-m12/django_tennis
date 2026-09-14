import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from tennis.models import Club


@override_settings(
    TIME_ZONE="Asia/Tokyo",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    },
)
class ClubAdminTests(TestCase):
    def test_changelist_displays_created_date_in_japan_time(self):
        club = Club.objects.create(name="作成日確認クラブ")
        Club.objects.filter(pk=club.pk).update(
            created_at=datetime.datetime(2026, 9, 11, 15, 30, tzinfo=datetime.timezone.utc)
        )

        admin_user = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="test-password",
        )
        self.client.force_login(admin_user)

        response = self.client.get(reverse("admin:tennis_club_changelist"))

        self.assertContains(response, "作成日")
        self.assertContains(response, "2026/09/12")
