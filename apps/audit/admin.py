from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ["occurred_at", "action_key", "entity_type", "actor_user", "department"]
    list_filter = ["action_key", "entity_type", "department"]
    search_fields = ["action_key", "entity_id", "actor_user__email", "request_id"]
    date_hierarchy = "occurred_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
