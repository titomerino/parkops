from django.contrib import messages

from payment.models import Subscription
from django.utils.timezone import localdate
from payment.models import Payment


def generate_current_month_payments():
    subscriptions = Subscription.objects.filter(active=True)

    for subscription in subscriptions:
        subscription.ensure_current_month_payment()

def get_pending_payments():
    """
    Devuelve todos los pagos pendientes que ya deben notificarse.
    """

    today = localdate()

    payments = (
        Payment.objects
        .select_related("subscription")
        .filter(paid=False)
        .order_by("subscription__name", "billing_date")
    )

    pending = []

    for payment in payments:

        # Si es del mes actual y aún no es día 22, no mostrarlo.
        if (
            payment.billing_date.year == today.year
            and payment.billing_date.month == today.month
            and today.day <= 22
        ):
            continue

        pending.append(payment)

    return pending

def notify_pending_payments(request):
    """
    Genera un mensaje de Django por cada pago pendiente.
    Antes asegura que exista el pago del mes de cada suscripción activa
    (get_or_create: no duplica aunque se llame en cada visita).
    """

    generate_current_month_payments()

    for payment in get_pending_payments():
        messages.error(request, str(payment))