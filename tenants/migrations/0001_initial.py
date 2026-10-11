import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Parking',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=150, verbose_name='Nombre')),
                ('address', models.CharField(blank=True, max_length=255, verbose_name='Dirección')),
                ('phone', models.CharField(blank=True, max_length=30, verbose_name='Teléfono')),
                ('capacity', models.PositiveIntegerField(blank=True, null=True, verbose_name='Espacios disponibles')),
                ('bathrooms_enabled', models.BooleanField(default=True, help_text='Si se desactiva, el parqueo no ve el menú, el dashboard ni las pantallas de baños', verbose_name='Módulo de baños')),
                ('active', models.BooleanField(default=True, help_text='Un parqueo suspendido no puede iniciar sesión', verbose_name='Activo')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Creado')),
            ],
            options={
                'verbose_name': 'Parqueo',
                'verbose_name_plural': 'Parqueos',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='ParkingMember',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('parking', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='members', to='tenants.parking', verbose_name='Parqueo')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='parking_membership', to=settings.AUTH_USER_MODEL, verbose_name='Usuario')),
            ],
            options={
                'verbose_name': 'Usuario del parqueo',
                'verbose_name_plural': 'Usuarios del parqueo',
            },
        ),
    ]
