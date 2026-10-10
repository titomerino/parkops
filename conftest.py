from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils.timezone import now

from parking.models import Entry, Fee, PlatePolicy, Range
from tenants.models import Parking, ParkingMember


@pytest.fixture
def parking(db):
    """Parqueo principal de las pruebas (el primero: el superusuario lo usa por defecto)."""
    return Parking.objects.create(name="Parqueo Central", address="Av. Principal 1", phone="2222-0000")


@pytest.fixture
def other_parking(db, parking):
    return Parking.objects.create(name="Parqueo Norte")


@pytest.fixture
def member(parking):
    """Asigna un usuario al parqueo (los usuarios no superusuarios lo necesitan)."""
    def assign(user, to=None):
        ParkingMember.objects.create(user=user, parking=to or parking)
        return user
    return assign


@pytest.fixture
def fee(parking):
    """Tarifa por bloques: $1 desde 0 min, $2 desde 60, $3 desde 120."""
    fee = Fee.objects.create(parking=parking, name="Normal", default=True)
    for minute, amount in [(0, "1.00"), (60, "2.00"), (120, "3.00")]:
        Range.objects.create(fee=fee, start_minute=minute, amount=Decimal(amount))
    return fee


@pytest.fixture
def make_entry(fee):
    def factory(plate="P123456", minutes_ago=90, duration=None, **kwargs):
        start = now() - timedelta(minutes=minutes_ago)
        departure = start + timedelta(minutes=duration) if duration is not None else None
        kwargs.setdefault("fee", fee)
        kwargs.setdefault("parking", kwargs["fee"].parking if kwargs["fee"] else fee.parking)
        entry = Entry(plate=plate, entry_date_hour=start, departure_date_hour=departure, **kwargs)
        entry.save()
        return entry
    return factory


@pytest.fixture
def monthly_policy(parking):
    return PlatePolicy.objects.create(parking=parking, plate="P100001", billing_type="MONTHLY", amount=Decimal("40.00"))


@pytest.fixture
def admin_client(client, django_user_model, parking):
    user = django_user_model.objects.create_superuser("admin", "a@a.com", "x")
    client.force_login(user)
    return client
