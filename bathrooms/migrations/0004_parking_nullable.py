# Paso 1 de multi-parqueo: columna parking opcional (se llena en tenants.0002)
import django.db.models.deletion
from django.db import migrations, models


def fk(related_name):
    return models.ForeignKey(
        null=True,
        on_delete=django.db.models.deletion.PROTECT,
        related_name=related_name,
        to='tenants.parking',
        verbose_name='Parqueo',
    )


class Migration(migrations.Migration):

    dependencies = [
        ('bathrooms', '0003_fee_on_delete_protect'),
        ('tenants', '0001_initial'),
    ]

    operations = [
        migrations.AddField(model_name='bathroomfee', name='parking', field=fk('bathroom_fees')),
        migrations.AddField(model_name='bathroomentry', name='parking', field=fk('bathroom_entries')),
    ]
