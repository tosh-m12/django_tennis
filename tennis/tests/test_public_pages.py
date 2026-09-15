from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from tennis import organizer_email
from tennis.models import Club, ClubOrganizer, EmailThrottle, Member


class PublicPagesTests(TestCase):
    def test_top_page_explains_the_service_and_links_to_public_pages(self):
        response = self.client.get(reverse("tennis:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "テニスサークル運営を")
        self.assertContains(response, "5つの機能を、ひとつに")
        self.assertContains(response, "その日の出席者リストから")
        self.assertContains(response, "クラブ内ランキング")
        self.assertContains(response, "ログインしなくても")
        self.assertContains(response, "tennis/landing/overview_v25/score.")
        self.assertContains(response, "tennis/landing/overview_v25/attendance.")
        self.assertContains(response, "tennis/landing/overview_v25/matchup-round-list-v2.")
        self.assertContains(response, 'id="club-registration-modal"')
        self.assertContains(response, "サークルURLを忘れた場合はこちら")
        self.assertContains(response, 'id="club-recovery-modal"')
        self.assertContains(response, f'action="{reverse("tennis:recover")}"')
        self.assertContains(response, reverse("tennis:demo"))
        self.assertContains(response, reverse("tennis:privacy"))
        self.assertContains(response, reverse("tennis:terms"))

    def test_club_name_only_does_not_create_club(self):
        response = self.client.post(
            reverse("tennis:index"),
            {"club_name": "青空テニス"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "お名前を入力してください。")
        self.assertEqual(Club.objects.count(), 0)
        self.assertEqual(Member.objects.count(), 0)
        self.assertEqual(ClubOrganizer.objects.count(), 0)

    @mock.patch("tennis.views.organizer_email.send_confirmation_email")
    def test_final_registration_creates_club_member_and_organizer_together(self, send_confirmation_email):
        response = self.client.post(
            reverse("tennis:index"),
            {
                "club_name": " 青空テニス ",
                "display_name": " 山田 太郎 ",
                "email": " Taro@Example.COM ",
            },
        )

        club = Club.objects.get()
        member = Member.objects.get()
        organizer = ClubOrganizer.objects.get()

        self.assertRedirects(response, reverse("tennis:index"))
        self.assertEqual(club.name, "青空テニス")
        self.assertEqual(member.club, club)
        self.assertEqual(member.member_no, 1)
        self.assertEqual(member.display_name, "山田 太郎")
        self.assertTrue(member.is_fixed)
        self.assertEqual(organizer.club, club)
        self.assertEqual(organizer.member, member)
        self.assertEqual(organizer.email, "taro@example.com")
        self.assertIsNone(organizer.confirmed_at)
        send_confirmation_email.assert_called_once_with(mock.ANY, organizer)

        completion = self.client.get(reverse("tennis:index"))
        expected_club_url = reverse(
            "tennis:club_home_admin",
            args=[club.admin_path_token, club.admin_token],
        )
        self.assertTrue(completion.context["registration_success"])
        self.assertContains(completion, "確認メールを送信しました")
        self.assertContains(
            completion,
            f'action="{reverse("tennis:club_registration_continue")}"',
        )
        self.assertNotContains(completion, expected_club_url)

        continue_response = self.client.post(
            reverse("tennis:club_registration_continue")
        )
        self.assertRedirects(continue_response, reverse("tennis:index"))
        self.assertFalse(
            self.client.get(reverse("tennis:index")).context[
                "registration_success"
            ]
        )

        token = organizer_email.make_confirm_token(organizer.id, organizer.email)
        verification = self.client.get(
            reverse("tennis:verify_email", args=[token])
        )
        self.assertContains(verification, "メールアドレスを確認しました")
        self.assertContains(verification, expected_club_url)
        self.assertContains(verification, "青空テニスを開く")

    def test_registration_continue_without_completed_registration_returns_to_top(self):
        response = self.client.post(reverse("tennis:club_registration_continue"))

        self.assertRedirects(response, reverse("tennis:index"))

    @mock.patch(
        "tennis.views.organizer_email.send_confirmation_email",
        side_effect=RuntimeError("mail unavailable"),
    )
    def test_email_failure_leaves_no_partial_club(self, _send_confirmation_email):
        response = self.client.post(
            reverse("tennis:index"),
            {
                "club_name": "青空テニス",
                "display_name": "山田 太郎",
                "email": "taro@example.com",
            },
        )

        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "登録できませんでした。", status_code=503)
        self.assertEqual(Club.objects.count(), 0)
        self.assertEqual(Member.objects.count(), 0)
        self.assertEqual(ClubOrganizer.objects.count(), 0)
        self.assertEqual(EmailThrottle.objects.count(), 0)

    @override_settings(EMAIL_DELIVERY_ENABLED=False)
    def test_missing_production_email_config_leaves_no_partial_club(self):
        response = self.client.post(
            reverse("tennis:index"),
            {
                "club_name": "青空テニス",
                "display_name": "山田 太郎",
                "email": "taro@example.com",
            },
        )

        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "現在メールを送信できません。", status_code=503)
        self.assertFalse(Club.objects.exists())
        self.assertFalse(Member.objects.exists())
        self.assertFalse(ClubOrganizer.objects.exists())

    def test_invalid_email_leaves_no_partial_club(self):
        response = self.client.post(
            reverse("tennis:index"),
            {
                "club_name": "青空テニス",
                "display_name": "山田 太郎",
                "email": "invalid-email",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "メールアドレスを確認してください。")
        self.assertFalse(Club.objects.exists())

    def test_privacy_policy_is_public(self):
        response = self.client.get(reverse("tennis:privacy"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "プライバシーポリシー")
        self.assertContains(response, "取得する情報")
        self.assertContains(response, "Google AdSense")
        self.assertContains(response, "Googleの広告設定")
        self.assertContains(response, "パーソナライズ広告を無効")

    def test_public_pages_include_adsense_ownership_meta(self):
        for route_name in ("tennis:index", "tennis:privacy", "tennis:terms"):
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                self.assertContains(
                    response,
                    '<meta name="google-adsense-account" content="ca-pub-3742846189705890">',
                    html=True,
                )

    def test_ads_txt_is_public(self):
        response = self.client.get(reverse("tennis:ads_txt"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/plain"))
        self.assertEqual(
            response.content.decode(),
            "google.com, pub-3742846189705890, DIRECT, f08c47fec0942fa0\n",
        )

    def test_terms_are_public(self):
        response = self.client.get(reverse("tennis:terms"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "利用規約")
        self.assertContains(response, "URLの管理")
        self.assertContains(response, "禁止事項")
