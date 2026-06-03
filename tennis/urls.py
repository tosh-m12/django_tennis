# tennis/urls.py
from django.contrib import admin
from django.urls import path

from . import views

app_name = "tennis"

urlpatterns = [
    # ============================================================
    # Django admin
    # ============================================================
    path("admin/", admin.site.urls),

    # ============================================================
    # Top
    #  - Create club
    # ============================================================
    path("", views.index, name="index"),

    # ============================================================
    # Club pages (token-based)
    # ============================================================
    path("c/<str:club_public_token>/", views.club_home, name="club_home"),
    path(
        "c/<str:club_public_token>/admin/<str:club_admin_token>/",
        views.club_home,
        name="club_home_admin",
    ),
    path(
        "c/<str:club_public_token>/admin/<str:club_admin_token>/settings/",
        views.club_settings,
        name="club_settings",
    ),
    path(
        "c/<str:club_public_token>/admin/<str:club_admin_token>/data/",
        views.club_data,
        name="club_data",
    ),
    path(
        "c/<str:club_public_token>/admin/<str:club_admin_token>/data/download/",
        views.club_data_download,
        name="club_data_download",
    ),
    path(
        "c/<str:club_public_token>/admin/<str:club_admin_token>/data/upload/",
        views.club_data_upload,
        name="club_data_upload",
    ),
    path(
        "c/<str:club_public_token>/admin/<str:club_admin_token>/data/apply/",
        views.club_data_apply,
        name="club_data_apply",
    ),
    path(
        "c/<str:club_public_token>/admin/<str:club_admin_token>/help/",
        views.club_admin_help,
        name="club_admin_help",
    ),
    path(
        "c/<str:club_public_token>/help/",
        views.club_user_help,
        name="club_user_help",
    ),
    path(
        "c/<str:club_public_token>/ranking/",
        views.ranking_page,
        name="ranking",
    ),
    path(
        "c/<str:club_public_token>/admin/<str:club_admin_token>/ranking/",
        views.ranking_page,
        name="ranking_admin",
    ),
    path(
        "c/<str:club_public_token>/member/<int:member_id>/",
        views.member_detail,
        name="member_detail",
    ),
    path(
        "c/<str:club_public_token>/admin/<str:club_admin_token>/member/<int:member_id>/",
        views.member_detail,
        name="member_detail_admin",
    ),

    # ============================================================
    # Event pages (token-based = club token)
    # ============================================================
    path(
        "c/<str:club_public_token>/event/<int:event_id>/",
        views.event_view,
        name="event_public",
    ),
    path(
        "c/<str:club_public_token>/admin/<str:club_admin_token>/event/<int:event_id>/",
        views.event_view,
        name="event_admin",
    ),
    # -- participant class (event scoped)
    path(
        "api/event/set_participant_class/",
        views.set_participant_class,
        name="set_participant_class",
    ),

    # ============================================================
    # Club APIs
    # ============================================================
    # -- flags (club-wide)
    path("api/club/add_flag/", views.club_add_flag, name="club_add_flag"),
    path("api/club/delete_flag/", views.club_delete_flag, name="club_delete_flag"),
    path("api/club/rename_flag/", views.club_rename_flag, name="club_rename_flag"),

    # -- club name
    path("api/club/rename_club/", views.club_rename_club, name="club_rename_club"),

    # -- events (settings calendar)
    path("api/club/create_event/", views.club_create_event, name="club_create_event"),
    path("api/club/cancel_event/", views.club_cancel_event, name="club_cancel_event"),
    path("api/club/delete_event/", views.club_delete_event, name="club_delete_event"),

    # -- members
    path("api/club/add_member/", views.club_add_member, name="club_add_member"),
    path("api/club/rename_member/", views.club_rename_member, name="club_rename_member"),
    path("api/club/toggle_member_fixed/", views.club_toggle_member_fixed, name="club_toggle_member_fixed"),
    path("api/club/delete_member/", views.club_delete_member, name="club_delete_member"),

    # NOTE: 既存URL互換のため prefix を変更しない（現状維持）
    path(
        "clubs/flag-input-mode/",
        views.club_set_flag_input_mode,
        name="club_set_flag_input_mode",
    ),

    # -- member classes
    path("club/class/add/", views.club_add_class, name="club_add_class"),
    path("club/class/rename/", views.club_rename_class, name="club_rename_class"),
    path("club/class/delete/", views.club_delete_class, name="club_delete_class"),
    path("club/class/set_member/", views.club_set_member_class, name="club_set_member_class"),

    # ============================================================
    # Event APIs (event scoped)
    # ============================================================
    path("api/event/add_event_flag/", views.add_event_flag, name="add_event_flag"),
    path("api/event/delete_event_flag/", views.delete_event_flag, name="delete_event_flag"),    
    path("api/event/update_attendance/", views.update_attendance, name="update_attendance"),
    path("api/event/update_comment/", views.update_comment, name="update_comment"),
    path("api/event/update_name/", views.update_participant_display_name, name="update_participant_display_name"),
    path("api/member/update_name/", views.update_member_display_name, name="update_member_display_name"),
    path("api/event/toggle_flag/", views.toggle_participant_flag, name="toggle_participant_flag"),
    path("api/event/set_participates_match/", views.set_participates_match, name="set_participates_match"),
    path("api/event/add_guest/", views.add_guest_participant, name="add_guest_participant"),
    path("api/event/set_flag_value/", views.set_participant_flag_value, name="set_participant_flag_value"),

    # ============================================================
    # Schedule / Publish
    # ============================================================
    path("ajax/generate_schedule/<int:event_id>/", views.ajax_generate_schedule, name="ajax_generate_schedule"),
    path("api/event/publish_schedule/", views.publish_schedule, name="publish_schedule"),

    # event meta update (title/place/time/cancelled)
    path("api/update_event/", views.ajax_update_event, name="ajax_update_event"),

    # display settings (event / club default)
    path("ajax/save_event_display_setting/", views.save_event_display_setting, name="save_event_display_setting"),
    path("ajax/save_club_display_setting/", views.save_club_display_setting, name="save_club_display_setting"),

    # ranking rule settings (club)
    path("ajax/save_club_ranking_setting/", views.save_club_ranking_setting, name="save_club_ranking_setting"),

    # ============================================================
    # Score
    # ============================================================
    path("api/match/save_score/", views.save_match_score, name="save_match_score"),

    # ============================================================
    # Substitute
    # ============================================================
    path("api/substitute_slot/", views.substitute_slot, name="substitute_slot"),
]
