# tennis/urls.py
from django.urls import path
from . import views

app_name = "tennis"

urlpatterns = [
    path("", views.index, name="index"),
    path("create/", views.create_event, name="create_event"),
    path("e/<str:public_token>/", views.event_public, name="event_public"),
    path("e/<str:public_token>/admin/<str:admin_token>/", views.event_admin, name="event_admin"),

    # AJAX（対戦表生成 / 公開）
    path("ajax/generate/<int:event_id>/", views.ajax_generate_schedule, name="ajax_generate_schedule"),
    path("ajax/publish/", views.publish_schedule, name="publish_schedule"),
]
