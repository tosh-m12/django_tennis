"""
一般メンバー向けヘルプページのテスト。
"""
from __future__ import annotations

from django.test import TestCase, override_settings
from django.urls import reverse

from .factories import make_club


_NO_MANIFEST_STORAGES = override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)


@_NO_MANIFEST_STORAGES
class UserHelpPageTests(TestCase):
    def setUp(self):
        self.club = make_club()
        self.url = reverse(
            "tennis:club_user_help",
            args=[self.club.public_token],
        )

    def test_renders_for_public_token(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["is_admin"])
        self.assertTrue(resp.context["show_topbar"])
        self.assertEqual(resp.context["club"].id, self.club.id)

    def test_404_for_unknown_public_token(self):
        bad_url = reverse(
            "tennis:club_user_help",
            args=["nonexistent-token-12345"],
        )
        resp = self.client.get(bad_url)
        self.assertEqual(resp.status_code, 404)

    def test_help_has_main_sections(self):
        resp = self.client.get(self.url)
        html = resp.content.decode()
        for needle in [
            "ホーム画面",
            "出欠の入力",
            "フラグ",
            "対戦表",
            "戦績",
            "個人ページ",
            "よくある質問",
        ]:
            self.assertIn(needle, html, f"missing section: {needle}")

    def test_topbar_has_help_link_on_public_page(self):
        # 一般ユーザー用ホームからtopbarにヘルプリンクが出ること
        home_url = reverse("tennis:club_home", args=[self.club.public_token])
        html = self.client.get(home_url).content.decode()
        self.assertIn('id="topbar-help-link"', html)
        self.assertIn(reverse("tennis:club_user_help", args=[self.club.public_token]), html)

    def test_admin_pages_link_to_admin_help_not_user_help(self):
        # 幹事URLの topbar は管理者ヘルプへ。一般ヘルプURLは出ない
        settings_url = reverse(
            "tennis:club_settings",
            args=[self.club.public_token, self.club.admin_token],
        )
        html = self.client.get(settings_url).content.decode()
        admin_help = reverse(
            "tennis:club_admin_help",
            args=[self.club.public_token, self.club.admin_token],
        )
        user_help = reverse("tennis:club_user_help", args=[self.club.public_token])
        self.assertIn(admin_help, html)
        self.assertNotIn(user_help, html)
