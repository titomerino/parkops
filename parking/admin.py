from django.contrib import admin

from parking.models import Entry, Fee, Range, PlatePolicy


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
