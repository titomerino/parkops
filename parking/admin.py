from django.contrib import admin

from django.db.models import Count, Sum

from parking.models import Entry, Fee, Range, PlatePolicy, PlateScan


class RangeInline(admin.TabularInline):
    model = Range
    extra = 0
    ordering = ("start_minute",)


@admin.register(Entry)
class EntryAdmin(admin.ModelAdmin):
    list_display = ('plate', 'parking', 'entry_date_hour', 'departure_date_hour', 'final_amount', 'state')
    list_filter = ('parking', 'state')
    list_select_related = ('parking',)
    search_fields = ('plate',)
    list_per_page = 20


@admin.register(Fee)
class FeeAdmin(admin.ModelAdmin):
    list_display = ('name', 'parking', 'default', 'is_active')
    list_filter = ('parking', 'is_active')
    list_select_related = ('parking',)
    inlines = [RangeInline]


@admin.register(PlatePolicy)
class PlatePolicyAdmin(admin.ModelAdmin):
    list_display = ("plate", "parking", "owner_name", "amount", "billing_type", "active")
    list_filter = ('parking', 'billing_type', 'active')
    list_select_related = ('parking',)
    search_fields = ('plate',)
    list_per_page = 20


@admin.register(PlateScan)
class PlateScanAdmin(admin.ModelAdmin):
    """Uso del escaneo con IA: para cobrarle a cada parqueo y ver el costo real."""

    list_display = ("created_at", "parking", "user", "plate", "input_tokens", "output_tokens", "cost")
    list_filter = ("parking",)
    list_select_related = ("parking", "user")
    date_hierarchy = "created_at"
    search_fields = ("plate",)
    list_per_page = 50

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context)

        # Totales del filtro actual (parqueo, mes...) arriba de la lista
        changelist = getattr(response, "context_data", {}).get("cl")
        if changelist is not None:
            response.context_data["scan_totals"] = changelist.queryset.aggregate(
                scans=Count("id"), cost=Sum("cost"),
            )
        return response
