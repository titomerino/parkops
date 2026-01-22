#!/bin/bash
set -e

echo "⏳ Esperando a la base de datos..."

until pg_isready -h "$DATABASE_HOST" -p "$DATABASE_PORT" -U "$DATABASE_USER"; do
  sleep 2
done

echo "✅ Base de datos lista"

echo "📦 Ejecutando migraciones..."
python manage.py migrate --noinput

echo "🚀 Iniciando Gunicorn..."
exec gunicorn parkopsbackend.wsgi:application --bind 0.0.0.0:8000
