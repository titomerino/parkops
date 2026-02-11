from django.contrib import admin
from parking.models import Configuration, Entry, Fee, Range, PlatePolicy


admin.site.register(Configuration)

@admin.register(Entry)
class EntryAdmin(admin.ModelAdmin):
    list_display = ('plate', 'entry_date_hour', 'departure_date_hour', 'state')

@admin.register(Range)
class RangeAdmin(admin.ModelAdmin):
    list_display = ('__str__',)

@admin.register(Fee)
class FeeAdmin(admin.ModelAdmin):
    list_display = ('name', 'default', 'is_active')

@admin.register(PlatePolicy)
class PlatePolicyAdmin(admin.ModelAdmin):
    list_display = ("plate", "owner_name", "amount", "billing_type", "active")