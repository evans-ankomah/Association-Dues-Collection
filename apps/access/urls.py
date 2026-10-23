from django.urls import path

from . import views

app_name = "access"

urlpatterns = [
    path("switch/", views.switch_context, name="switch"),
]
