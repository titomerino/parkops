from decimal import Decimal

import pytest
from django.db.models import ProtectedError

from bathrooms.models import BathroomEntry, BathroomFee


@pytest.mark.django_db
def test_no_se_puede_borrar_tarifa_de_bano_con_usos():
    fee = BathroomFee.objects.create(name="Sanitario", amount=Decimal("0.25"))
    BathroomEntry.objects.create(fee=fee)
    with pytest.raises(ProtectedError):
        fee.delete()
    assert BathroomEntry.objects.count() == 1
