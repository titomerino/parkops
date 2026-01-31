from django.contrib import admin
from parking.models import Configuration, Entry, Fee, PlatePolicy


admin.site.register(Configuration)

@admin.register(Entry)
class EntryAdmin(admin.ModelAdmin):
    list_display = ('plate', 'entry_date_hour', 'departure_date_hour', 'state')
    readonly_fields = ('entry_date_hour', 'state')

@admin.register(Fee)
class FeeAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'amount', 'duration_hours', 'default')

@admin.register(PlatePolicy)
class PlatePolicyAdmin(admin.ModelAdmin):
    list_display = ("plate", "owner_name", "amount", "billing_type", "active")