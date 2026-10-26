from django.urls import path

from . import views

app_name = "members"

urlpatterns = [
    path("", views.roster, name="roster"),
    path("import/", views.roster_import, name="import"),
    path("<uuid:pk>/", views.member_detail, name="detail"),
]
