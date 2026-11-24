from django.contrib import admin

from audit.models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    """Solo lectura: la auditoría no se edita."""

    list_display = ("created_at", "parking", "username", "action", "target", "summary", "ip")
    list_filter = ("parking", "action")
    search_fields = ("username", "target", "summary")
    date_hierarchy = "created_at"
    list_select_related = ("parking",)
    list_per_page = 50

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
