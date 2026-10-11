# Paso 1 de multi-parqueo: columna parking opcional (se llena en tenants.0002)
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payment', '0002_subscription_on_delete_protect'),
        ('tenants', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='subscription',
            name='parking',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='subscriptions',
                to='tenants.parking',
                verbose_name='Parqueo',
            ),
        ),
    ]
