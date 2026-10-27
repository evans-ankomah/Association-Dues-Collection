from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    path("", views.document_list, name="documents"),
    path("upload/", views.document_upload, name="upload"),
    path("<uuid:pk>/", views.document_detail, name="detail"),
    path("<uuid:pk>/download/", views.download, name="download"),
    path("<uuid:pk>/action/", views.document_action, name="action"),
]
