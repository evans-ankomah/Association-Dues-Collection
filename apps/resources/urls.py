from django.urls import path

from . import views

app_name = "resources"

urlpatterns = [
    path("", views.asset_list, name="assets"),
    path("new/", views.asset_form, name="asset_create"),
    path("bookings/", views.booking_list, name="bookings"),
    path("bookings/<uuid:pk>/action/", views.booking_action, name="booking_action"),
    path("<uuid:pk>/", views.asset_detail, name="asset"),
    path("<uuid:pk>/edit/", views.asset_form, name="asset_edit"),
    path("<uuid:pk>/book/", views.book, name="book"),
]
