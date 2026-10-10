# Paso 3 de multi-parqueo: parking obligatorio
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payment', '0003_parking_nullable'),
        ('tenants', '0002_assign_principal_parking'),
    ]

    operations = [
        migrations.AlterField(
            model_name='subscription',
            name='parking',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='subscriptions',
                to='tenants.parking',
                verbose_name='Parqueo',
            ),
        ),
    ]
