import datetime
from unittest import mock

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
    @mock.patch("tennis.views.organizer_email.send_confirmation_email")
    def test_registration_email_is_saved_on_club(self, _send_confirmation_email):
        response = self.client.post(
            reverse("tennis:index"),
            {
                "club_name": "登録者確認クラブ",
                "display_name": "山田",
                "email": " Owner@Example.COM ",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Club.objects.get().registered_by_email, "owner@example.com")

    def test_changelist_and_detail_display_registration_email(self):
        club = Club.objects.create(
            name="登録者確認クラブ",
            registered_by_email="owner@example.com",
        )
        admin_user = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="test-password",
        )
        self.client.force_login(admin_user)

        changelist = self.client.get(reverse("admin:tennis_club_changelist"))
        self.assertContains(changelist, "登録者メールアドレス")
        self.assertContains(changelist, "owner@example.com")

        detail = self.client.get(reverse("admin:tennis_club_change", args=[club.pk]))
        self.assertContains(detail, "登録者メールアドレス")
        self.assertContains(detail, "owner@example.com")

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

    def test_changelist_displays_last_accessed_datetime_in_japan_time(self):
        club = Club.objects.create(name="最終アクセス確認クラブ")
        Club.objects.filter(pk=club.pk).update(
            last_accessed_at=datetime.datetime(
                2026, 9, 11, 16, 45, tzinfo=datetime.timezone.utc
            )
        )

        admin_user = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="test-password",
        )
        self.client.force_login(admin_user)

        response = self.client.get(reverse("admin:tennis_club_changelist"))

        self.assertContains(response, "最終アクセス日時")
        self.assertContains(response, "2026/09/12 01:45")
