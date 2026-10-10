"""
Carga datos de demostración para desarrollo local.

Genera ~60 días de operación (parqueo, suscripciones y baños) e incluye
a propósito casos que pueden existir en producción:

- Entradas antiguas sin final_minutes / final_amount (anteriores a la migración 0011).
- Una placa con dos entradas activas (posible por condición de carrera).
- Suscripción mensual sin monto y suscripción por hora.
- Tarifa cuyo primer rango no inicia en el minuto 0.

Uso:
    python manage.py seed_demo --reset
"""
import random
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from bathrooms.models import BathroomEntry, BathroomFee
from parking.models import Entry, Fee, PlatePolicy, Range

DAYS = 60
LEGACY_DAYS = 50  # entradas con más antigüedad quedan sin montos congelados
DUPLICATE_PLATE = "P555555"

MONTHLY_PLATES = ["P100001", "P100002", "P100003"]
DAILY_PLATES = ["P200001", "P200002"]
HOURLY_PLATE = "P300001"
INACTIVE_PLATE = "P400001"


class Command(BaseCommand):
    help = "Carga datos de demostración (solo para entorno local)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Elimina entradas, tarifas, suscripciones y baños antes de cargar",
        )
        parser.add_argument("--seed", type=int, default=42)

    def handle(self, *args, **options):
        import os

        if os.getenv("DJANGO_ENV", "local") == "production":
            raise CommandError("seed_demo no puede ejecutarse en producción")

        if Entry.objects.exists() and not options["reset"]:
            raise CommandError("Ya existen datos. Usa --reset para reemplazarlos.")

        self.rng = random.Random(options["seed"])
        self.tz = timezone.get_current_timezone()
        self.now = timezone.localtime(timezone.now())

        with transaction.atomic():
            if options["reset"]:
                self._reset()

            fees = self._create_fees()
            self._create_policies()
            self._create_parking_entries(fees)
            self._create_legacy_entries()
            self._create_duplicate_active()
            self._create_bathroom_data()
            self._create_operator()

        self._print_summary()

    # ------------------------------------------------------------------ #

    def _reset(self):
        BathroomEntry.objects.all().delete()
        BathroomFee.objects.all().delete()
        Entry.objects.all().delete()
        Range.objects.all().delete()
        Fee.objects.all().delete()
        PlatePolicy.objects.all().delete()

    def _create_fees(self):
        def fee(name, ranges, **kwargs):
            obj = Fee.objects.create(name=name, **kwargs)
            Range.objects.bulk_create(
                Range(fee=obj, start_minute=m, amount=Decimal(a)) for m, a in ranges
            )
            return obj

        return {
            "normal": fee(
                "Normal",
                [(0, "1.00"), (60, "2.00"), (120, "3.00"), (240, "5.00"), (480, "8.00")],
                default=True,
                description="Tarifa estándar por bloques",
            ),
            "nocturna": fee(
                "Nocturna",
                [(0, "3.00"), (720, "6.00")],
                description="Estadía nocturna",
            ),
            # Primer rango en minuto 15: calculate_fee falla con menos tiempo
            "promo": fee(
                "Promo 15 min gratis",
                [(15, "1.00"), (60, "2.00"), (180, "4.00")],
                description="Primeros 15 minutos sin cobro",
            ),
        }

    def _create_policies(self):
        PlatePolicy.objects.bulk_create([
            PlatePolicy(plate="P100001", billing_type="MONTHLY", amount=Decimal("40.00"), owner_name="Ana López"),
            PlatePolicy(plate="P100002", billing_type="MONTHLY", amount=Decimal("40.00"), owner_name="Carlos Pérez"),
            # Mensual sin monto: el formulario lo permite
            PlatePolicy(plate="P100003", billing_type="MONTHLY", amount=None, owner_name="Clínica Central"),
            PlatePolicy(plate="P200001", billing_type="DAILY", amount=Decimal("3.00"), owner_name="María Gómez"),
            PlatePolicy(plate="P200002", billing_type="DAILY", amount=Decimal("2.50"), owner_name="José Martínez"),
            PlatePolicy(plate=HOURLY_PLATE, billing_type="HOURLY", amount=Decimal("1.00"), owner_name="Luis Ramírez"),
            PlatePolicy(plate=INACTIVE_PLATE, billing_type="MONTHLY", amount=Decimal("35.00"), owner_name="Ex cliente", active=False),
        ])

    def _regular_plates(self):
        plates = set()
        while len(plates) < 70:
            prefix = self.rng.choices(["P", "M", "C"], weights=[85, 10, 5])[0]
            digits = self.rng.choice([5, 6])
            plates.add(prefix + str(self.rng.randint(10 ** (digits - 1), 10 ** digits - 1)))
        return sorted(plates)

    def _create_parking_entries(self, fees):
        regular = self._regular_plates()
        self.stats = {"closed": 0, "active": 0}
        active_plates = set()

        for days_ago in range(DAYS, -1, -1):
            day = (self.now - timedelta(days=days_ago)).date()
            weekend = day.weekday() >= 5

            visitors = self.rng.sample(regular, self.rng.randint(8, 14) if weekend else self.rng.randint(15, 25))
            visits = [(p, "regular") for p in visitors]

            if not weekend:
                visits += [(p, "monthly") for p in MONTHLY_PLATES if self.rng.random() < 0.8]
                visits += [(p, "daily") for p in DAILY_PLATES if self.rng.random() < 0.6]
            if self.rng.random() < 0.5:
                visits.append((HOURLY_PLATE, "hourly"))
            if self.rng.random() < 0.3:
                visits.append((INACTIVE_PLATE, "regular"))

            for plate, kind in visits:
                if plate in active_plates:
                    continue

                start = datetime.combine(day, time(6, 0), tzinfo=self.tz) + timedelta(
                    minutes=self.rng.randint(0, 15 * 60)
                )
                if start >= self.now:
                    continue

                fee = None
                if kind == "monthly":
                    duration = self.rng.randint(480, 600)
                elif kind == "daily":
                    duration = self.rng.randint(240, 600)
                else:
                    bucket = self.rng.choices(["short", "medium", "long", "night"], weights=[40, 40, 15, 5])[0]
                    duration = {
                        "short": lambda: self.rng.randint(15, 60),
                        "medium": lambda: self.rng.randint(60, 240),
                        "long": lambda: self.rng.randint(240, 600),
                        "night": lambda: self.rng.randint(720, 900),
                    }[bucket]()
                    if bucket == "night":
                        fee = fees["nocturna"]
                    elif self.rng.random() < 0.1:
                        fee = fees["promo"]
                    else:
                        fee = fees["normal"]

                departure = start + timedelta(minutes=duration)
                if departure > self.now:
                    departure = None
                    active_plates.add(plate)

                # save() calcula final_minutes / final_amount como en producción
                Entry(
                    plate=plate,
                    entry_date_hour=start,
                    departure_date_hour=departure,
                    fee=fee,
                ).save()
                self.stats["active" if departure is None else "closed"] += 1

    def _create_legacy_entries(self):
        limit = self.now - timedelta(days=LEGACY_DAYS)
        self.stats["legacy"] = Entry.objects.filter(
            departure_date_hour__lt=limit
        ).update(final_minutes=None, final_amount=None)

    def _create_duplicate_active(self):
        # bulk_create omite la validación de save(): simula una condición de carrera
        start = self.now - timedelta(minutes=45)
        Entry.objects.bulk_create([
            Entry(plate=DUPLICATE_PLATE, entry_date_hour=start, fee=Fee.objects.get(default=True)),
            Entry(plate=DUPLICATE_PLATE, entry_date_hour=start + timedelta(seconds=2), fee=Fee.objects.get(default=True)),
        ])

    def _create_bathroom_data(self):
        sanitario = BathroomFee.objects.create(name="Sanitario", amount=Decimal("0.25"), color="primary")
        ducha = BathroomFee.objects.create(name="Ducha", amount=Decimal("1.00"), color="info")
        ninos = BathroomFee.objects.create(name="Sanitario niños", amount=Decimal("0.10"), color="warning", state=False)

        times = []
        fees = []
        for days_ago in range(DAYS, -1, -1):
            day = (self.now - timedelta(days=days_ago)).date()
            count = self.rng.randint(60, 120) if day.weekday() >= 5 else self.rng.randint(40, 80)
            for _ in range(count):
                moment = datetime.combine(day, time(6, 0), tzinfo=self.tz) + timedelta(
                    minutes=self.rng.randint(0, 15 * 60)
                )
                if moment >= self.now:
                    continue
                options = [sanitario, ducha] + ([ninos] if days_ago > 20 else [])
                weights = [70, 20] + ([10] if days_ago > 20 else [])
                times.append(moment)
                fees.append(self.rng.choices(options, weights=weights)[0])

        entries = BathroomEntry.objects.bulk_create(BathroomEntry(fee=f) for f in fees)
        # auto_now_add ignora el valor asignado: se corrige la fecha después
        for entry, moment in zip(entries, times):
            entry.entry_date_hour = moment
        BathroomEntry.objects.bulk_update(entries, ["entry_date_hour"], batch_size=500)

    def _create_operator(self):
        User = get_user_model()
        user, _ = User.objects.get_or_create(username="operador")
        user.set_password("default")
        user.is_staff = False
        user.is_superuser = False
        user.save()
        user.user_permissions.set(Permission.objects.filter(
            content_type__app_label__in=["parking", "bathrooms"],
            codename__in=[
                "add_entry", "view_entry",
                "view_platepolicy",
                "add_bathroomentry", "view_bathroomentry",
            ],
        ))

    def _print_summary(self):
        self.stdout.write(self.style.SUCCESS("Datos de demostración cargados"))
        self.stdout.write(f"  Entradas cerradas:        {self.stats['closed']}")
        self.stdout.write(f"  Entradas activas:         {self.stats['active'] + 2}")
        self.stdout.write(f"  Entradas legacy (sin $):  {self.stats['legacy']}")
        self.stdout.write(f"  Placa duplicada activa:   {DUPLICATE_PLATE}")
        self.stdout.write(f"  Suscripciones:            {PlatePolicy.objects.count()}")
        self.stdout.write(f"  Usos de baño:             {BathroomEntry.objects.count()}")
        self.stdout.write("  Usuario operador:         operador / default")
