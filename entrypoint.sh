#!/bin/bash
set -e

echo "⏳ Esperando a la base de datos..."

if [ -n "$DATABASE_URL" ]; then
  echo "🔗 Usando DATABASE_URL"
  until pg_isready -d "$DATABASE_URL"; do
    sleep 2
  done
else
  echo "🔗 Usando PG* variables"
  until pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER"; do
    sleep 2
  done
fi

echo "✅ Base de datos lista"

echo "📦 Recolectando archivos estáticos..."
python manage.py collectstatic --noinput

echo "📦 Ejecutando migraciones..."
python manage.py migrate --noinput

echo "👑 Creando superuser si no existe..."
python manage.py shell <<EOF
from django.contrib.auth import get_user_model
import os

User = get_user_model()

username = os.getenv("DJANGO_SUPERUSER_USERNAME")
email = os.getenv("DJANGO_SUPERUSER_EMAIL")
password = os.getenv("DJANGO_SUPERUSER_PASSWORD")

if username and password:
    if not User.objects.filter(username=username).exists():
        User.objects.create_superuser(username, email, password)
        print("✅ Superuser creado")
    else:
        print("ℹ️ Superuser ya existe")
else:
    print("⚠️ Variables de superuser no definidas, saltando...")
EOF

# Un solo worker (valor por defecto) atiende una petición a la vez: un PDF o
# reporte lento bloqueaba al resto de usuarios. Ajustable desde Railway.
echo "🚀 Iniciando Gunicorn (workers=${WEB_CONCURRENCY:-3}, timeout=${GUNICORN_TIMEOUT:-60}s)..."
exec gunicorn parkopsbackend.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers "${WEB_CONCURRENCY:-3}" \
  --timeout "${GUNICORN_TIMEOUT:-60}" \
  --access-logfile -
