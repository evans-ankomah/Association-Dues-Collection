from django.contrib import admin

from .models import DepartmentMembership


@admin.register(DepartmentMembership)
class DepartmentMembershipAdmin(admin.ModelAdmin):
    list_display = ["user", "department", "academic_session", "level_code", "membership_status"]
    list_filter = ["department", "academic_session", "membership_status", "level_code"]
    search_fields = ["user__email", "user__profile__student_number", "user__profile__family_name"]
    raw_id_fields = ["user", "verified_by"]
