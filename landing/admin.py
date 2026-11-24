from urllib.parse import quote

from django.contrib import admin
from django.utils.html import format_html

from .models import Lead


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'business_name', 'contact_name', 'whatsapp_link', 'plan', 'status', 'follow_up_on')
    list_display_links = ('created_at', 'business_name')
    list_editable = ('status', 'follow_up_on')
    list_filter = ('status', 'plan')
    list_select_related = ('plan',)
    search_fields = ('business_name', 'contact_name', 'whatsapp', 'notes')
    date_hierarchy = 'created_at'
    readonly_fields = ('whatsapp_link', 'ip', 'created_at', 'updated_at')
    autocomplete_fields = ('parking',)
    fieldsets = (
        ('Solicitud', {'fields': ('business_name', 'contact_name', 'whatsapp', 'whatsapp_link', 'plan', 'created_at')}),
        ('Seguimiento', {'fields': ('status', 'follow_up_on', 'notes', 'parking')}),
        ('Datos técnicos', {'fields': ('ip', 'updated_at'), 'classes': ('collapse',)}),
    )
    actions = ('mark_contacted',)

    @admin.display(description="WhatsApp")
    def whatsapp_link(self, obj):
        if not obj.whatsapp:
            return "—"
        text = quote(
            f"Hola {obj.contact_name}, te saluda ParkOps. Recibimos tu solicitud de prueba gratis "
            f"para {obj.business_name}. ¿Te parece si coordinamos la configuración?"
        )
        return format_html(
            '<a href="https://wa.me/{}?text={}" target="_blank" rel="noopener">{}</a>',
            obj.whatsapp, text, obj.whatsapp_display,
        )

    @admin.action(description="Marcar como contactado")
    def mark_contacted(self, request, queryset):
        updated = queryset.filter(status=Lead.NEW).update(status=Lead.CONTACTED)
        self.message_user(request, f"{updated} solicitud(es) marcadas como contactadas.")
