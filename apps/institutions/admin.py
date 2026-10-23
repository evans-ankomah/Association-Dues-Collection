from django.contrib import admin

from .models import AcademicSession, Department, Faculty, Institution


@admin.register(Institution)
class InstitutionAdmin(admin.ModelAdmin):
    list_display = ["name", "country_code", "default_currency", "status"]


@admin.register(Faculty)
class FacultyAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "institution", "status"]
    list_filter = ["institution", "status"]


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "faculty", "institution", "status"]
    list_filter = ["institution", "faculty", "status"]
    search_fields = ["name", "code"]


@admin.register(AcademicSession)
class AcademicSessionAdmin(admin.ModelAdmin):
    list_display = ["name", "institution", "starts_on", "ends_on", "is_current", "status"]
    list_filter = ["institution", "status"]
