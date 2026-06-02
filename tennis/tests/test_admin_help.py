"""
幹事向けヘルプページのテスト。
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
class AdminHelpPageTests(TestCase):
    def setUp(self):
        self.club = make_club()
        self.url = reverse(
            "tennis:club_admin_help",
            args=[self.club.public_token, self.club.admin_token],
        )

    def test_renders_for_valid_admin_token(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["is_admin"])
        self.assertTrue(resp.context["show_topbar"])
        self.assertEqual(resp.context["club"].id, self.club.id)

    def test_404_for_wrong_admin_token(self):
        bad_url = reverse(
            "tennis:club_admin_help",
            args=[self.club.public_token, "wrongtoken"],
        )
        resp = self.client.get(bad_url)
        self.assertEqual(resp.status_code, 404)

    def test_help_has_main_sections(self):
        resp = self.client.get(self.url)
        html = resp.content.decode()
        # 主要セクションの見出しが含まれていること（仕様維持の特性テスト）
        for needle in [
            "幹事向けヘルプ",
            "メンバー管理",
            "イベント管理",
            "参加登録",
            "フラグ機能",
            "対戦表",
            "戦績ページ",
            "データ集計表",
            "デフォルト表示設定",
            "困ったときは",
        ]:
            self.assertIn(needle, html, f"missing section: {needle}")

    def test_topbar_has_help_link_when_admin(self):
        # 設定ページから取って topbar にヘルプリンクが出ること
        settings_url = reverse(
            "tennis:club_settings",
            args=[self.club.public_token, self.club.admin_token],
        )
        html = self.client.get(settings_url).content.decode()
        self.assertIn('id="topbar-help-link"', html)
        self.assertIn("ヘルプ", html)
