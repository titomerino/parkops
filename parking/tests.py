from datetime import timedelta
from decimal import Decimal

import pytest
from django.db.models import ProtectedError

from parking.models import Entry


@pytest.mark.django_db
class TestFeeProtect:
    def test_no_se_puede_borrar_tarifa_con_entradas(self, fee, make_entry):
        make_entry(duration=30)
        with pytest.raises(ProtectedError):
            fee.delete()
        assert Entry.objects.count() == 1

    def test_se_puede_borrar_tarifa_sin_uso(self, fee):
        fee.delete()
