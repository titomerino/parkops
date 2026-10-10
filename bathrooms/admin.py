from django.contrib import admin
from bathrooms.models import BathroomFee, BathroomEntry


@admin.register(BathroomFee)
class BathroomFeeAdmin(admin.ModelAdmin):
    list_display = ('name', 'parking', 'amount', 'state')
    list_filter = ('parking', 'state')
    list_select_related = ('parking',)


@admin.register(BathroomEntry)
class BathroomEntryAdmin(admin.ModelAdmin):
    list_display = ('entry_date_hour', 'parking', 'fee')
    list_filter = ('parking',)
    list_select_related = ('parking', 'fee')
