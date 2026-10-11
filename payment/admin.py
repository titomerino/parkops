from django.contrib import admin, messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.html import format_html

from parking.utils import render_pdf_response
from payment.models import BillingProfile, Invoice, InvoiceLine, Payment, Plan, Subscription
from payment.services.invoice_service import balance_due, generate_invoice, month_label


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'ai_package', 'active', 'subscriptions_count')
    list_filter = ('active',)
    list_select_related = ('ai_package',)

    @admin.display(description="Parqueos activos")
    def subscriptions_count(self, obj):
        return obj.subscriptions.filter(active=True).count()


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('name', 'parking', 'plan', 'price', 'activation_date', 'active')
    list_filter = ('parking', 'plan', 'active')
    list_select_related = ('parking', 'plan')
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


class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLine
    extra = 0
    can_delete = False
    fields = ("kind", "description", "detail", "amount", "paid")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("number", "parking", "period_label", "total", "balance", "issued_at", "pdf_link")
    list_filter = ("parking", "period")
    list_select_related = ("parking",)
    fields = ("parking", "period", "issued_at", "total", "notes")
    readonly_fields = ("parking", "period", "issued_at", "total")
    inlines = [InvoiceLineInline]
    actions = ["regenerate"]

    def has_add_permission(self, request):
        # Se generan desde Parqueos → acción «Generar factura»
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("lines")

    @admin.display(description="Número", ordering="pk")
    def number(self, obj):
        return obj.number

    @admin.display(description="Mes", ordering="period")
    def period_label(self, obj):
        return month_label(obj.period)

    @admin.display(description="Pendiente")
    def balance(self, obj):
        due = balance_due(obj)
        return f"${due:.2f}" if due else "Pagada"

    @admin.display(description="PDF")
    def pdf_link(self, obj):
        return format_html('<a href="{}" target="_blank">Ver PDF</a>', reverse("admin:payment_invoice_pdf", args=[obj.pk]))

    @admin.action(description="Volver a generar (tras recargas o pagos)")
    def regenerate(self, request, queryset):
        for invoice in queryset.select_related("parking"):
            generate_invoice(invoice.parking, invoice.period)
        self.message_user(request, f"{queryset.count()} factura(s) actualizada(s).", messages.SUCCESS)

    def get_urls(self):
        return [
            path("<int:pk>/pdf/", self.admin_site.admin_view(self.pdf_view), name="payment_invoice_pdf"),
        ] + super().get_urls()

    def pdf_view(self, request, pk):
        invoice = get_object_or_404(Invoice.objects.select_related("parking"), pk=pk)
        lines = list(invoice.lines.all())
        balance = balance_due(invoice)

        return render_pdf_response(
            request,
            "payment/invoice_pdf.html",
            {
                "invoice": invoice,
                "lines": lines,
                "profile": BillingProfile.load(),
                "period_label": month_label(invoice.period),
                "balance": balance,
                "paid_total": invoice.total - balance,
            },
            f"factura-{invoice.number}.pdf",
        )


@admin.register(BillingProfile)
class BillingProfileAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        BillingProfile.load()
        return redirect(reverse("admin:payment_billingprofile_change", args=[1]))
