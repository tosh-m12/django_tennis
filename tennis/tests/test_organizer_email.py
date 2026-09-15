from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from tennis import organizer_email
from tennis.models import ClubOrganizer

from .factories import make_club, make_member


class OrganizerEmailTests(TestCase):
    def setUp(self):
        self.club = make_club()
        self.owner = make_member(self.club, "山田", is_fixed=True)
        self.owner_org = ClubOrganizer.objects.create(
            club=self.club,
            member=self.owner,
            email="owner@example.com",
            confirmed_at=timezone.now(),
        )
        self.member = make_member(self.club, "佐藤", is_fixed=False)

    def admin_post(self, name, data):
        return self.client.post(
            reverse(name),
            {"club_id": self.club.id, "admin_token": self.club.admin_token, **data},
        )

    def test_settings_shows_organizer_checkbox_and_email_only_for_organizers(self):
        response = self.client.get(
            reverse(
                "tennis:club_settings",
                args=[self.club.public_token, self.club.admin_token],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<th>幹事</th>", html=True)
        self.assertContains(response, "owner@example.com")
        self.assertContains(response, "member-organizer-toggle is-on")
        self.assertNotContains(response, "member-organizer-select")
        self.assertContains(response, "URLリセット")
        self.assertContains(response, "メンバー用URLをリセット")
        self.assertContains(response, "幹事用URLをリセット")
        html = response.content.decode()
        self.assertLess(html.index("データ整理"), html.index("URLリセット"))

    def test_settings_unconfirmed_badge_opens_resend_modal(self):
        self.owner_org.confirmed_at = None
        self.owner_org.save(update_fields=["confirmed_at", "updated_at"])

        response = self.client.get(
            reverse(
                "tennis:club_settings",
                args=[self.club.public_token, self.club.admin_token],
            )
        )

        self.assertContains(response, "member-email-resend")
        self.assertContains(response, 'data-email="owner@example.com"')
        self.assertContains(response, "確認メールを再送")
        self.assertContains(
            response,
            reverse("tennis:organizer_resend_confirmation"),
        )

    @mock.patch("tennis.views.organizer_email.send_confirmation_email")
    def test_resend_confirmation_sends_to_unconfirmed_email(self, send_mail):
        self.owner_org.confirmed_at = None
        self.owner_org.save(update_fields=["confirmed_at", "updated_at"])

        response = self.admin_post(
            "tennis:organizer_resend_confirmation",
            {"member_id": self.owner.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"], "確認メールを再送しました。")
        send_mail.assert_called_once_with(
            mock.ANY,
            self.owner_org,
            target_email="owner@example.com",
        )

    @mock.patch("tennis.views.organizer_email.send_confirmation_email")
    def test_resend_confirmation_uses_pending_email(self, send_mail):
        self.owner_org.pending_email = "new@example.com"
        self.owner_org.save(update_fields=["pending_email", "updated_at"])

        response = self.admin_post(
            "tennis:organizer_resend_confirmation",
            {"member_id": self.owner.id},
        )

        self.assertEqual(response.status_code, 200)
        send_mail.assert_called_once_with(
            mock.ANY,
            self.owner_org,
            target_email="new@example.com",
        )

    @mock.patch("tennis.views.organizer_email.send_confirmation_email")
    def test_resend_confirmation_rejects_confirmed_email(self, send_mail):
        response = self.admin_post(
            "tennis:organizer_resend_confirmation",
            {"member_id": self.owner.id},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "not_pending")
        send_mail.assert_not_called()

    @mock.patch("tennis.views.organizer_email.send_confirmation_email")
    def test_resend_confirmation_cannot_target_another_club(self, send_mail):
        other_club = make_club("別クラブ")
        other_member = make_member(other_club, "別幹事", is_fixed=True)
        ClubOrganizer.objects.create(
            club=other_club,
            member=other_member,
            email="other@example.com",
        )

        response = self.admin_post(
            "tennis:organizer_resend_confirmation",
            {"member_id": other_member.id},
        )

        self.assertEqual(response.status_code, 404)
        send_mail.assert_not_called()

    def test_assigning_organizer_creates_role_and_fixes_member(self):
        response = self.admin_post(
            "tennis:club_set_member_organizer",
            {"member_id": self.member.id, "role": "organizer"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_organizer"])
        self.assertEqual(response.json()["email"], "")
        self.assertFalse(response.json()["email_unconfirmed"])
        self.assertTrue(ClubOrganizer.objects.filter(club=self.club, member=self.member).exists())
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_fixed)

    def test_new_organizer_gets_email_section_only_on_admin_member_page(self):
        ClubOrganizer.objects.create(club=self.club, member=self.member)
        admin_url = reverse(
            "tennis:member_detail_admin",
            args=[self.club.public_token, self.club.admin_token, self.member.id],
        )
        public_url = reverse(
            "tennis:member_detail",
            args=[self.club.public_token, self.member.id],
        )

        admin_response = self.client.get(admin_url)
        public_response = self.client.get(public_url)

        self.assertContains(admin_response, "登録メールアドレス")
        self.assertContains(admin_response, "メールアドレスを保存すると確認メールが送られます")
        self.assertContains(admin_response, reverse("tennis:organizer_set_email"))
        self.assertNotContains(public_response, "登録メールアドレス")
        self.assertNotContains(public_response, reverse("tennis:organizer_set_email"))

    def test_registered_email_uses_same_editable_input_and_save_pattern_as_display_name(self):
        response = self.client.get(
            reverse(
                "tennis:member_detail_admin",
                args=[self.club.public_token, self.club.admin_token, self.owner.id],
            )
        )

        self.assertContains(response, 'id="member-name-input"')
        self.assertContains(response, 'id="organizer-email-input"')
        self.assertContains(response, 'class="member-field-input"', count=2)
        self.assertContains(response, 'value="owner@example.com"')
        self.assertNotContains(response, 'id="organizer-email-change-btn"')
        self.assertNotContains(response, "readonly")

        html = response.content.decode()
        self.assertLess(
            html.index('id="organizer-email-save-btn"'),
            html.index('id="organizer-email-status"'),
        )

    @mock.patch("tennis.views.organizer_email.send_confirmation_email")
    def test_confirmed_email_change_keeps_old_email_until_new_one_is_verified(self, send_mail):
        original_confirmed_at = self.owner_org.confirmed_at

        response = self.admin_post(
            "tennis:organizer_set_email",
            {"member_id": self.owner.id, "email": "NEW@EXAMPLE.COM"},
        )

        self.assertEqual(response.status_code, 200)
        self.owner_org.refresh_from_db()
        self.assertEqual(self.owner_org.email, "owner@example.com")
        self.assertEqual(self.owner_org.pending_email, "new@example.com")
        self.assertEqual(self.owner_org.confirmed_at, original_confirmed_at)
        send_mail.assert_called_once_with(
            mock.ANY, self.owner_org, target_email="new@example.com"
        )

        token = organizer_email.make_confirm_token(self.owner_org.id, "new@example.com")
        verify_response = self.client.get(
            reverse("tennis:verify_email", args=[token])
        )

        self.assertEqual(verify_response.status_code, 200)
        self.assertContains(verify_response, self.club.name)
        club_url = reverse(
            "tennis:club_home_admin",
            args=[self.club.admin_path_token, self.club.admin_token],
        )
        self.assertContains(verify_response, club_url)
        self.assertContains(verify_response, f"{self.club.name}を開く")
        self.assertNotContains(
            verify_response,
            f'<a href="{club_url}" class="btn btn-pill btn-primary">',
        )
        self.owner_org.refresh_from_db()
        self.assertEqual(self.owner_org.email, "new@example.com")
        self.assertEqual(self.owner_org.pending_email, "")
        self.assertIsNotNone(self.owner_org.confirmed_at)

    @mock.patch("tennis.views.organizer_email.send_confirmation_email")
    def test_unconfirmed_email_can_be_replaced_before_confirmation(self, send_mail):
        self.owner_org.email = "mistake@example.com"
        self.owner_org.confirmed_at = None
        self.owner_org.save(update_fields=["email", "confirmed_at", "updated_at"])

        response = self.admin_post(
            "tennis:organizer_set_email",
            {"member_id": self.owner.id, "email": "correct@example.com"},
        )

        self.assertEqual(response.status_code, 200)
        self.owner_org.refresh_from_db()
        self.assertEqual(self.owner_org.email, "correct@example.com")
        self.assertEqual(self.owner_org.pending_email, "")
        self.assertIsNone(self.owner_org.confirmed_at)
        self.assertEqual(
            response.json()["message"],
            "確認メールをおくりました。メール内のリンクを開くと登録完了です",
        )
        send_mail.assert_called_once_with(
            mock.ANY, self.owner_org, target_email="correct@example.com"
        )

    def test_pending_email_is_not_used_for_recovery_before_confirmation(self):
        self.owner_org.pending_email = "new@example.com"
        self.owner_org.save(update_fields=["pending_email", "updated_at"])

        with mock.patch("tennis.views.organizer_email.send_recovery_email") as send_recovery:
            self.client.post(reverse("tennis:recover"), {"email": "new@example.com"})
            send_recovery.assert_not_called()

            self.client.post(reverse("tennis:recover"), {"email": "owner@example.com"})
            send_recovery.assert_called_once()

    @mock.patch("tennis.views.organizer_email.send_url_reset_email")
    def test_public_url_reset_invalidates_only_old_public_url_and_emails_confirmed_organizers(self, send_email):
        duplicate = make_member(self.club, "重複メール幹事")
        unconfirmed = make_member(self.club, "未確認幹事")
        ClubOrganizer.objects.create(
            club=self.club,
            member=duplicate,
            email="OWNER@example.com",
            confirmed_at=timezone.now(),
        )
        ClubOrganizer.objects.create(
            club=self.club,
            member=unconfirmed,
            email="pending@example.com",
        )
        old_public_token = self.club.public_token
        old_admin_path_token = self.club.admin_path_token
        old_admin_token = self.club.admin_token
        old_admin_url = reverse(
            "tennis:club_settings",
            args=[old_admin_path_token, old_admin_token],
        )

        response = self.admin_post(
            "tennis:club_reset_url",
            {"reset_kind": "public"},
        )

        self.assertEqual(response.status_code, 200)
        self.club.refresh_from_db()
        self.assertNotEqual(self.club.public_token, old_public_token)
        self.assertEqual(self.club.admin_path_token, old_admin_path_token)
        self.assertEqual(self.club.admin_token, old_admin_token)
        self.assertEqual(response.json()["settings_url"], f"http://testserver{old_admin_url}")
        self.assertEqual(response.json()["sent_count"], 1)
        send_email.assert_called_once_with(
            mock.ANY, "owner@example.com", self.club, "public"
        )
        old_url = reverse("tennis:club_home", args=[old_public_token])
        new_url = reverse("tennis:club_home", args=[self.club.public_token])
        self.assertEqual(self.client.get(old_url).status_code, 404)
        self.assertEqual(self.client.get(new_url).status_code, 200)
        self.assertEqual(self.client.get(old_admin_url).status_code, 200)

    @mock.patch("tennis.views.organizer_email.send_url_reset_email")
    def test_admin_url_reset_invalidates_old_admin_url_and_returns_new_settings_url(self, send_email):
        old_public_token = self.club.public_token
        old_admin_token = self.club.admin_token

        response = self.admin_post(
            "tennis:club_reset_url",
            {"reset_kind": "admin"},
        )

        self.assertEqual(response.status_code, 200)
        self.club.refresh_from_db()
        self.assertEqual(self.club.public_token, old_public_token)
        self.assertNotEqual(self.club.admin_token, old_admin_token)
        self.assertIn(self.club.admin_token, response.json()["settings_url"])
        send_email.assert_called_once_with(
            mock.ANY, "owner@example.com", self.club, "admin"
        )
        old_url = reverse(
            "tennis:club_settings", args=[old_public_token, old_admin_token]
        )
        new_url = reverse(
            "tennis:club_settings",
            args=[self.club.admin_path_token, self.club.admin_token],
        )
        self.assertEqual(self.client.get(old_url).status_code, 404)
        self.assertEqual(self.client.get(new_url).status_code, 200)

    @mock.patch("tennis.views.organizer_email.send_url_reset_email")
    def test_url_reset_does_not_change_another_club(self, _send_email):
        other_club = make_club("別サークル")
        other_public_token = other_club.public_token
        other_admin_token = other_club.admin_token

        response = self.admin_post(
            "tennis:club_reset_url",
            {"reset_kind": "public"},
        )

        self.assertEqual(response.status_code, 200)
        other_club.refresh_from_db()
        self.assertEqual(other_club.public_token, other_public_token)
        self.assertEqual(other_club.admin_token, other_admin_token)

    def test_one_club_admin_token_cannot_reset_another_club_url(self):
        other_club = make_club("別サークル")
        other_public_token = other_club.public_token
        other_admin_token = other_club.admin_token

        response = self.client.post(
            reverse("tennis:club_reset_url"),
            {
                "club_id": other_club.id,
                "admin_token": self.club.admin_token,
                "reset_kind": "public",
            },
        )

        self.assertEqual(response.status_code, 403)
        other_club.refresh_from_db()
        self.assertEqual(other_club.public_token, other_public_token)
        self.assertEqual(other_club.admin_token, other_admin_token)

    @mock.patch("tennis.views.organizer_email.send_url_reset_email")
    def test_url_reset_requires_a_confirmed_organizer_email(self, send_email):
        self.owner_org.confirmed_at = None
        self.owner_org.save(update_fields=["confirmed_at", "updated_at"])
        old_public_token = self.club.public_token
        old_admin_token = self.club.admin_token

        for reset_kind in ("public", "admin"):
            with self.subTest(reset_kind=reset_kind):
                response = self.admin_post(
                    "tennis:club_reset_url",
                    {"reset_kind": reset_kind},
                )
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()["error"], "confirmed_email_required")

        self.club.refresh_from_db()
        self.assertEqual(self.club.public_token, old_public_token)
        self.assertEqual(self.club.admin_token, old_admin_token)
        send_email.assert_not_called()

    @override_settings(EMAIL_DELIVERY_ENABLED=False)
    @mock.patch("tennis.views.organizer_email.send_url_reset_email")
    def test_url_reset_does_not_change_tokens_when_email_delivery_is_unavailable(self, send_email):
        old_public_token = self.club.public_token
        old_admin_token = self.club.admin_token

        for reset_kind in ("public", "admin"):
            with self.subTest(reset_kind=reset_kind):
                response = self.admin_post(
                    "tennis:club_reset_url",
                    {"reset_kind": reset_kind},
                )
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["error"], "email_unavailable")

        self.club.refresh_from_db()
        self.assertEqual(self.club.public_token, old_public_token)
        self.assertEqual(self.club.admin_token, old_admin_token)
        send_email.assert_not_called()

    @mock.patch(
        "tennis.views.organizer_email.send_url_reset_email",
        side_effect=RuntimeError("mail unavailable"),
    )
    def test_url_reset_keeps_current_tokens_when_all_email_sends_fail(self, send_email):
        old_public_token = self.club.public_token
        old_admin_token = self.club.admin_token

        for reset_kind in ("public", "admin"):
            with self.subTest(reset_kind=reset_kind):
                response = self.admin_post(
                    "tennis:club_reset_url",
                    {"reset_kind": reset_kind},
                )
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["error"], "email_failed")

        self.club.refresh_from_db()
        self.assertEqual(self.club.public_token, old_public_token)
        self.assertEqual(self.club.admin_token, old_admin_token)
        self.assertEqual(send_email.call_count, 2)

    def test_public_url_reset_email_contains_correct_recipient_subject_and_new_url(self):
        old_public_token = self.club.public_token

        response = self.admin_post(
            "tennis:club_reset_url",
            {"reset_kind": "public"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["owner@example.com"])
        self.assertIn("メンバー用URLを再発行しました", message.subject)
        self.assertIn(response.json()["new_url"], message.body)
        self.assertNotIn(old_public_token, message.body)

    def test_admin_url_reset_email_contains_correct_recipient_subject_and_new_url(self):
        old_admin_token = self.club.admin_token

        response = self.admin_post(
            "tennis:club_reset_url",
            {"reset_kind": "admin"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["owner@example.com"])
        self.assertIn("幹事用URLを再発行しました", message.subject)
        self.assertIn(response.json()["new_url"], message.body)
        self.assertNotIn(old_admin_token, message.body)

    @mock.patch(
        "tennis.views.organizer_email.send_confirmation_email",
        side_effect=RuntimeError("mail unavailable"),
    )
    def test_email_send_failure_does_not_leave_pending_change(self, _send_mail):
        response = self.admin_post(
            "tennis:organizer_set_email",
            {"member_id": self.owner.id, "email": "new@example.com"},
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"], "email_failed")
        self.owner_org.refresh_from_db()
        self.assertEqual(self.owner_org.email, "owner@example.com")
        self.assertEqual(self.owner_org.pending_email, "")
        self.assertIsNotNone(self.owner_org.confirmed_at)
