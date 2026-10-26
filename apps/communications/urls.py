from django.urls import path

from . import views

app_name = "communications"

urlpatterns = [
    path("announcements/", views.announcement_list, name="announcements"),
    path("announcements/manage/", views.manage, name="manage"),
    path("announcements/new/", views.edit, name="create"),
    path("announcements/<uuid:pk>/", views.announcement_detail, name="announcement"),
    path("announcements/<uuid:pk>/edit/", views.edit, name="edit"),
    path("announcements/<uuid:pk>/status/", views.change_status, name="status"),
    path("announcements/<uuid:pk>/acknowledge/", views.acknowledge, name="acknowledge"),
    path("notifications/", views.notification_list, name="notifications"),
    path("notifications/bell/", views.bell, name="bell"),
    path("notifications/read-all/", views.mark_all_read, name="mark_all_read"),
    path("notifications/<uuid:pk>/", views.open_notification, name="open"),
]
