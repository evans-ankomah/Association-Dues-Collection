from django.urls import path

from . import views

app_name = "events"

urlpatterns = [
    path("", views.event_list, name="events"),
    path("new/", views.event_form, name="create"),
    path("<uuid:pk>/", views.event_detail, name="detail"),
    path("<uuid:pk>/edit/", views.event_form, name="edit"),
    path("<uuid:pk>/action/", views.event_action, name="action"),
    path("<uuid:pk>/register/", views.register, name="register"),
    path("<uuid:pk>/attendance/", views.attendance, name="attendance"),
    path("<uuid:pk>/attendance/check-in/", views.check_in, name="check_in"),
    path("<uuid:pk>/attendance/search/", views.member_search, name="member_search"),
    path("registrations/<uuid:pk>/cancel/", views.cancel_registration, name="cancel_registration"),
]
