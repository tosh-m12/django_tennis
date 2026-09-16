import datetime
from unittest import mock

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from tennis.models import Club, Event, MatchSchedule, MatchScore, Member


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

    def test_changelist_displays_compact_usage_summary(self):
        club = Club.objects.create(
            name="利用実績確認クラブ",
            last_accessed_at=timezone.now(),
        )
        Member.objects.create(club=club, display_name="山田", is_fixed=True)
        Member.objects.create(club=club, display_name="佐藤", is_fixed=True)
        event_with_result = Event.objects.create(
            club=club,
            title="練習1",
            date=datetime.date(2026, 9, 1),
        )
        Event.objects.create(
            club=club,
            title="練習2",
            date=datetime.date(2026, 9, 8),
        )
        schedule = MatchSchedule.objects.create(
            event=event_with_result,
            schedule_json={},
            game_type="doubles",
            court_count=1,
            round_count=2,
            published=True,
        )
        MatchScore.objects.create(
            match_schedule=schedule,
            round_no=1,
            court_no=1,
            side_a_score=6,
            side_b_score=3,
        )
        MatchScore.objects.create(
            match_schedule=schedule,
            round_no=2,
            court_no=1,
        )
        admin_user = get_user_model().objects.create_superuser(
            username="usage-admin",
            email="usage-admin@example.com",
            password="test-password",
        )
        self.client.force_login(admin_user)

        response = self.client.get(reverse("admin:tennis_club_changelist"))

        self.assertContains(response, "利用実績")
        self.assertContains(response, "メンバー 2")
        self.assertContains(response, "イベント 2")
        self.assertContains(response, "試合結果 1")
        result = next(
            item for item in response.context["cl"].result_list if item.pk == club.pk
        )
        self.assertEqual(result._member_count, 2)
        self.assertEqual(result._event_count, 2)
        self.assertEqual(result._match_result_count, 1)

        club_admin = admin.site._registry[Club]
        self.assertNotIn("public_token", club_admin.list_display)
        self.assertNotIn("admin_token", club_admin.list_display)
        self.assertIn("public_token", club_admin.readonly_fields)
        self.assertIn("admin_token", club_admin.readonly_fields)

    def test_activity_filter_separates_recent_inactive_and_never_accessed_clubs(self):
        recent = Club.objects.create(
            name="最近利用クラブ",
            last_accessed_at=timezone.now() - datetime.timedelta(days=5),
        )
        inactive = Club.objects.create(
            name="休止クラブ",
            last_accessed_at=timezone.now() - datetime.timedelta(days=45),
        )
        never = Club.objects.create(name="未アクセスクラブ")
        admin_user = get_user_model().objects.create_superuser(
            username="filter-admin",
            email="filter-admin@example.com",
            password="test-password",
        )
        self.client.force_login(admin_user)
        url = reverse("admin:tennis_club_changelist")

        recent_response = self.client.get(url, {"activity": "recent"})
        self.assertContains(recent_response, recent.name)
        self.assertNotContains(recent_response, inactive.name)
        self.assertNotContains(recent_response, never.name)

        inactive_response = self.client.get(url, {"activity": "inactive"})
        self.assertNotContains(inactive_response, recent.name)
        self.assertContains(inactive_response, inactive.name)
        self.assertNotContains(inactive_response, never.name)

        never_response = self.client.get(url, {"activity": "never"})
        self.assertNotContains(never_response, recent.name)
        self.assertNotContains(never_response, inactive.name)
        self.assertContains(never_response, never.name)
