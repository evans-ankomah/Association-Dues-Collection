from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

from apps.common.views import healthz

admin.site.site_header = "DeptHub administration"
admin.site.site_title = "DeptHub admin"

urlpatterns = [
    path("", TemplateView.as_view(template_name="home.html"), name="home"),
    path("healthz/", healthz, name="healthz"),
    path("accounts/", include("apps.accounts.urls")),
    path("context/", include("apps.access.urls")),
    path("finance/", include("apps.finance.urls")),
    path("members/", include("apps.memberships.urls")),
    path("communications/", include("apps.communications.urls")),
    path("django-admin/", admin.site.urls),
]
