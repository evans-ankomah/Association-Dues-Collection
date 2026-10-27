from django.urls import path

from . import views

app_name = "service_requests"

urlpatterns = [
    path("", views.request_list, name="requests"),
    path("new/", views.request_form, name="create"),
    path("<uuid:pk>/", views.request_detail, name="detail"),
    path("<uuid:pk>/action/", views.request_action, name="action"),
]
