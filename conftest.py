from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils.timezone import now

from parking.models import Entry, Fee, PlatePolicy, Range


@pytest.fixture
def fee(db):
    """Tarifa por bloques: $1 desde 0 min, $2 desde 60, $3 desde 120."""
    fee = Fee.objects.create(name="Normal", default=True)
    for minute, amount in [(0, "1.00"), (60, "2.00"), (120, "3.00")]:
        Range.objects.create(fee=fee, start_minute=minute, amount=Decimal(amount))
    return fee


@pytest.fixture
def make_entry(fee):
    def factory(plate="P123456", minutes_ago=90, duration=None, **kwargs):
        start = now() - timedelta(minutes=minutes_ago)
        departure = start + timedelta(minutes=duration) if duration is not None else None
        kwargs.setdefault("fee", fee)
        entry = Entry(plate=plate, entry_date_hour=start, departure_date_hour=departure, **kwargs)
        entry.save()
        return entry
    return factory


@pytest.fixture
def monthly_policy(db):
    return PlatePolicy.objects.create(plate="P100001", billing_type="MONTHLY", amount=Decimal("40.00"))


@pytest.fixture
def admin_client(client, django_user_model):
    user = django_user_model.objects.create_superuser("admin", "a@a.com", "x")
    client.force_login(user)
    return client
