from django.urls import path

from .views import dues, member, waivers

app_name = "finance"

urlpatterns = [
    path("my-dues/", member.my_dues, name="my_dues"),
    path("dues/", dues.dues_type_list, name="dues_types"),
    path("dues/new/", dues.dues_type_create, name="dues_type_create"),
    path("dues/<uuid:pk>/", dues.dues_type_detail, name="dues_type"),
    path("dues/<uuid:pk>/edit/", dues.dues_type_edit, name="dues_type_edit"),
    path("dues/<uuid:pk>/status/", dues.dues_type_status, name="dues_type_status"),
    path("dues/<uuid:pk>/assess/", dues.assess, name="assess"),
    path("assessments/<uuid:pk>/", dues.assessment_detail, name="assessment"),
    path("assessments/<uuid:pk>/waiver/", dues.request_waiver, name="request_waiver"),
    path("assessments/<uuid:pk>/cancel/", dues.cancel_assessment, name="cancel_assessment"),
    path("waivers/", waivers.waiver_list, name="waivers"),
    path("waivers/<uuid:pk>/decide/", waivers.decide_waiver, name="decide_waiver"),
]
