from django.contrib import admin

from .models import Permission, Role, RoleAssignment, RolePermission


class RolePermissionInline(admin.TabularInline):
    model = RolePermission
    extra = 0
    raw_id_fields = ["created_by"]


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ["name", "role_code", "scope_type", "is_system_role"]
    inlines = [RolePermissionInline]


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ["permission_code", "module_key", "action_key", "description"]
    list_filter = ["module_key"]


@admin.register(RoleAssignment)
class RoleAssignmentAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "role",
        "department",
        "academic_session",
        "assignment_status",
        "starts_at",
        "ends_at",
    ]
    list_filter = ["role", "department", "assignment_status"]
    search_fields = ["user__email"]
    raw_id_fields = ["user", "assigned_by"]

    def save_model(self, request, obj, form, change):
        if not change and obj.assigned_by_id is None:
            obj.assigned_by = request.user
        obj.full_clean()
        super().save_model(request, obj, form, change)
