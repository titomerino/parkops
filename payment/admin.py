from django.contrib import admin
from payment.models import Subscription, Payment



@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'activation_date', 'price', 'active')
    search_fields = ('name',)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('__str__','subscription', 'billing_date', 'amount', 'paid')
    list_editable = ('paid',)
    search_fields = ('subscription__name', 'billing_date')
    list_per_page = 20