# Paso 3 de multi-parqueo: parking obligatorio, reglas por parqueo e índices
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
        ('parking', '0016_parking_nullable'),
        ('tenants', '0002_assign_principal_parking'),
    ]

    operations = [
        migrations.AlterField(model_name='fee', name='parking', field=fk('fees')),
        migrations.AlterField(model_name='entry', name='parking', field=fk('entries')),
        migrations.AlterField(model_name='platepolicy', name='parking', field=fk('plate_policies')),

        # Entrada activa por placa: de global a por parqueo
        migrations.RemoveConstraint(model_name='entry', name='unique_active_entry_per_plate'),
        migrations.AddConstraint(
            model_name='entry',
            constraint=models.UniqueConstraint(
                condition=models.Q(('state', True)),
                fields=('parking', 'plate'),
                name='unique_active_entry_per_plate',
            ),
        ),

        # Placa de suscripción: de única global a única por parqueo
        migrations.AlterField(
            model_name='platepolicy',
            name='plate',
            field=models.CharField(max_length=10, verbose_name='Placa'),
        ),
        migrations.AddConstraint(
            model_name='platepolicy',
            constraint=models.UniqueConstraint(fields=('parking', 'plate'), name='unique_plate_policy_per_parking'),
        ),

        # Una tarifa por defecto en cada parqueo
        migrations.AddConstraint(
            model_name='fee',
            constraint=models.UniqueConstraint(
                condition=models.Q(('default', True)),
                fields=('parking',),
                name='unique_default_fee_per_parking',
            ),
        ),

        migrations.AddIndex(
            model_name='entry',
            index=models.Index(fields=['parking', 'entry_date_hour'], name='entry_parking_entry_idx'),
        ),
        migrations.AddIndex(
            model_name='entry',
            index=models.Index(fields=['parking', 'departure_date_hour'], name='entry_parking_departure_idx'),
        ),
        migrations.AddIndex(
            model_name='entry',
            index=models.Index(fields=['parking', 'state'], name='entry_parking_state_idx'),
        ),

        # Configuration (sin uso y vacío) lo reemplaza tenants.Parking
        migrations.DeleteModel(name='Configuration'),
    ]
