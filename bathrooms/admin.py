from django.contrib import admin
from bathrooms.models import BathroomFee, BathroomEntry


@admin.register(BathroomFee)
class BathroomFeeAdmin(admin.ModelAdmin):
    list_display = ('name', 'amount', 'state')


@admin.register(BathroomEntry)
class BathroomEntryAdmin(admin.ModelAdmin):
    list_display = ('entry_date_hour', 'fee')
