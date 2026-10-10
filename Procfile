web: python manage.py migrate && gunicorn parkopsbackend.wsgi:application --workers ${WEB_CONCURRENCY:-3} --timeout ${GUNICORN_TIMEOUT:-60}
