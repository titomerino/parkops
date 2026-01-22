#!/bin/bash
set -e

echo "⏳ Esperando a la base de datos..."

# Railway siempre provee DATABASE_URL
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

echo "📦 Ejecutando migraciones..."
python manage.py migrate --noinput

echo "🚀 Iniciando Gunicorn..."
exec gunicorn parkopsbackend.wsgi:application --bind 0.0.0.0:8000
