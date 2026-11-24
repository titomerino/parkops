from django.core.management.base import BaseCommand

from audit.services import RETENTION_DAYS, purge_old


class Command(BaseCommand):
    help = "Borra los eventos de auditoría con más de 12 meses (se ejecuta en cada despliegue)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=RETENTION_DAYS)

    def handle(self, *args, days, **options):
        self.stdout.write(f"Eventos de auditoría borrados: {purge_old(days)}")
