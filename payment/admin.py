from django.contrib import admin
from payment.models import Subscription, Payment



@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('name', 'parking', 'price', 'activation_date', 'active')
    list_filter = ('parking', 'active')
    list_select_related = ('parking',)
    search_fields = ('name', 'parking__name')


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'subscription', 'parking_name', 'billing_date', 'amount', 'paid')
    list_filter = ('subscription__parking', 'paid')
    list_select_related = ('subscription__parking',)
    list_editable = ('paid',)
    search_fields = ('subscription__name', 'billing_date')
    list_per_page = 20

    @admin.display(description="Parqueo", ordering="subscription__parking__name")
    def parking_name(self, obj):
        return obj.subscription.parking.name