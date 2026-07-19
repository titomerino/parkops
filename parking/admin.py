from django.contrib import admin
from parking.models import Configuration, Entry, Fee, Range, PlatePolicy


admin.site.register(Configuration)

@admin.register(Entry)
class EntryAdmin(admin.ModelAdmin):
    list_display = (
        'plate',
        'entry_date_hour',
        'departure_date_hour',
        'final_amount',
        'state',
        'created_by',
        'created_at'
    )
    readonly_fields = (
        "created_by",
        "created_at",
    )
    search_fields = ('plate', "created_by__username",)
    list_per_page = 20

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user

        super().save_model(request, obj, form, change)

@admin.register(Range)
class RangeAdmin(admin.ModelAdmin):
    list_display = ('__str__',)

@admin.register(Fee)
class FeeAdmin(admin.ModelAdmin):
    list_display = ('name', 'default', 'is_active')

@admin.register(PlatePolicy)
class PlatePolicyAdmin(admin.ModelAdmin):
    list_display = ("plate", "owner_name", "amount", "billing_type", "active")
    search_fields = ('plate',)
    list_per_page = 20