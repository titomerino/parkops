# Paso 3 de multi-parqueo: parking obligatorio e índice
import django.db.models.deletion
from django.db import migrations, models


def fk(related_name):
    return models.ForeignKey(
        on_delete=django.db.models.deletion.PROTECT,
        related_name=related_name,
        to='tenants.parking',
        verbose_name='Parqueo',
    )


class Migration(migrations.Migration):

    dependencies = [
        ('bathrooms', '0004_parking_nullable'),
        ('tenants', '0002_assign_principal_parking'),
    ]

    operations = [
        migrations.AlterField(model_name='bathroomfee', name='parking', field=fk('bathroom_fees')),
        migrations.AlterField(model_name='bathroomentry', name='parking', field=fk('bathroom_entries')),
        migrations.AddIndex(
            model_name='bathroomentry',
            index=models.Index(fields=['parking', 'entry_date_hour'], name='bathentry_parking_entry_idx'),
        ),
    ]
