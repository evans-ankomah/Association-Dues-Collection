from django.urls import path

from .views import dues, member, online, payments, waivers

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
    path("my-payments/", payments.my_payments, name="my_payments"),
    path("payments/", payments.payment_list, name="payments"),
    path("payments/record/", payments.record_payment, name="record_payment"),
    path("payments/member-search/", payments.member_search, name="member_search"),
    path("payments/<uuid:pk>/", payments.payment_detail, name="payment"),
    path("payments/<uuid:pk>/verify/", payments.verify_payment, name="verify_payment"),
    path("payments/<uuid:pk>/reject/", payments.reject_payment, name="reject_payment"),
    path("payments/<uuid:pk>/cancel/", payments.cancel_payment, name="cancel_payment"),
    path("receipts/<uuid:pk>/", payments.receipt_detail, name="receipt"),
    path("receipts/<uuid:pk>/pdf/", payments.receipt_pdf, name="receipt_pdf"),
    path("pay/", online.pay_online, name="pay_online"),
    path("pay/callback/", online.paystack_callback, name="paystack_callback"),
    path("pay/status/<str:reference>/", online.online_status, name="online_status"),
    path("webhooks/paystack/", online.paystack_webhook, name="paystack_webhook"),
]
