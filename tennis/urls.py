# tennis/urls.py
from django.urls import path
from . import views

app_name = "tennis"

urlpatterns = [
    # 1) ポータル（クラブ作成）
    path("", views.portal_index, name="portal_index"),

    # 2) クラブメイン（メンバー用）
    path("c/<str:club_public_token>/", views.club_main, name="club_main"),

    # 3) 練習会画面（イベント単位・全員共通）
    path("c/<str:club_public_token>/e/<int:event_id>/", views.event_detail, name="event_detail"),

    # 4) クラブ設定（幹事用）
    path(
        "c/<str:club_public_token>/admin/<str:club_admin_token>/settings/",
        views.club_settings,
        name="club_settings",
    ),
    path("api/club/<str:club_public_token>/events/create/", views.api_event_create, name="api_event_create"),


    # ---- API（BETA） ----
    path("api/club/<str:club_public_token>/flags/add/", views.api_flag_add, name="api_flag_add"),
    path("api/club/<str:club_public_token>/flags/<int:flag_id>/rename/", views.api_flag_rename, name="api_flag_rename"),
    path("api/club/<str:club_public_token>/flags/<int:flag_id>/toggle_active/", views.api_flag_toggle_active, name="api_flag_toggle_active"),

    path("api/club/<str:club_public_token>/members/add/", views.api_member_add, name="api_member_add"),

    path("api/event/<int:event_id>/attendance/update/", views.api_attendance_update, name="api_attendance_update"),
    path("api/event/<int:event_id>/schedule/generate/", views.api_schedule_generate, name="api_schedule_generate"),
    path("api/event/<int:event_id>/score/set/", views.api_score_set, name="api_score_set"),
    path("api/event/<int:event_id>/schedule/reset/", views.api_schedule_reset, name="api_schedule_reset"),
    path("api/event/<int:event_id>/schedule/swap_player/", views.api_schedule_swap_player, name="api_schedule_swap_player"),

]
