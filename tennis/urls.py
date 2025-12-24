# tennis/urls.py
from django.contrib import admin
from django.urls import path, include
from . import views

app_name = "tennis"

urlpatterns = [
    path("admin/", admin.site.urls),
    # top (create club)
    path("", views.index, name="index"),

    # club
    path("c/<str:club_public_token>/", views.club_home, name="club_home"),
    path("c/<str:club_public_token>/admin/<str:club_admin_token>/", views.club_home, name="club_home_admin"),
    path(
        "c/<str:club_public_token>/admin/<str:club_admin_token>/settings/",
        views.club_settings,
        name="club_settings",
    ),

    # event (token-based = club token)
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

    # club flags (club-wide)
    path("api/club/add_flag/", views.club_add_flag, name="club_add_flag"),
    path("api/club/delete_flag/", views.club_delete_flag, name="club_delete_flag"),
    path("api/club/rename_flag/", views.club_rename_flag, name="club_rename_flag"),

    # club name
    path("api/club/rename_club/", views.club_rename_club, name="club_rename_club"),

    # events on settings calendar
    path("api/club/create_event/", views.club_create_event, name="club_create_event"),
    path("api/club/cancel_event/", views.club_cancel_event, name="club_cancel_event"),
    path("api/club/delete_event/", views.club_delete_event, name="club_delete_event"),

    # participants (event scoped)
    path("api/event/update_attendance/", views.update_attendance, name="update_attendance"),
    path("api/event/update_comment/", views.update_comment, name="update_comment"),
    path("api/event/toggle_flag/", views.toggle_participant_flag, name="toggle_participant_flag"),
    path("api/event/set_participates_match/", views.set_participates_match, name="set_participates_match"),
    path("api/event/add_guest/", views.add_guest_participant, name="add_guest_participant"),

    # schedule
    path(
        "ajax/generate_schedule/<int:event_id>/",
        views.ajax_generate_schedule,
        name="ajax_generate_schedule",
    ),
    path("api/event/publish_schedule/", views.publish_schedule, name="publish_schedule"),
    path("api/update_event/", views.ajax_update_event, name="ajax_update_event"),


    # score
    path("api/match/save_score/", views.save_match_score, name="save_match_score"),

    path("api/club/add_member/", views.club_add_member, name="club_add_member"),
    path("api/club/rename_member/", views.club_rename_member, name="club_rename_member"),
    path("api/club/toggle_member_fixed/", views.club_toggle_member_fixed, name="club_toggle_member_fixed"),

]
