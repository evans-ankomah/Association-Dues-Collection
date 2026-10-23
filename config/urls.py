from django.contrib import admin
from django.urls import path
from django.views.generic import TemplateView

from apps.common.views import healthz

urlpatterns = [
    path("", TemplateView.as_view(template_name="home.html"), name="home"),
    path("healthz/", healthz, name="healthz"),
    path("django-admin/", admin.site.urls),
]
