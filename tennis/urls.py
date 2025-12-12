# tennis/urls.py
from django.urls import path
from . import views

app_name = "tennis"

urlpatterns = [
    path("", views.index, name="index"),
    path("create/", views.create_event, name="create_event"),
    
    path("e/<str:public_token>/", views.event_public, name="event_public"),
    path(
        "e/<str:public_token>/admin/<str:admin_token>/",
        views.event_admin,
        name="event_admin",
    ),
    path(
        "settings/",
        views.club_settings,     # ← 後述の新ビュー
        name="settings",
    ),
    path(
        "api/update_participation_flag/",
        views.update_participation_flag,
        name="update_participation_flag",
    ),
    path("api/add_flag/", views.add_flag, name="add_flag"),
    path("delete_flag/", views.delete_flag, name="delete_flag"),
    path("api/rename_flag/", views.rename_flag, name="rename_flag"),
    path("api/toggle_flag/", views.toggle_flag, name="toggle_flag"),
    path("publish-schedule/", views.publish_schedule, name="publish_schedule"),
    path(
        "ajax/generate_schedule/<int:event_id>/",
        views.ajax_generate_schedule,
        name="ajax_generate_schedule",
    ),
]
