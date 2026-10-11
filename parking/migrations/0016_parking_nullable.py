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
        ('parking', '0015_unique_active_entry_per_plate'),
        ('tenants', '0001_initial'),
    ]

    operations = [
        migrations.AddField(model_name='fee', name='parking', field=fk('fees')),
        migrations.AddField(model_name='entry', name='parking', field=fk('entries')),
        migrations.AddField(model_name='platepolicy', name='parking', field=fk('plate_policies')),
    ]
