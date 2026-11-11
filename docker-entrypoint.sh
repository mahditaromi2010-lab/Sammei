#!/bin/sh
set -e
export FLASK_APP=wsgi
# Seed categories/products only when the shop is empty (safe to run every start).
flask seed
if [ -n "$ADMIN_USERNAME" ] && [ -n "$ADMIN_PASSWORD" ]; then
  flask create-admin "$ADMIN_USERNAME"
fi
exec gunicorn wsgi:app --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_WORKERS:-2} --threads 4 --timeout 60 --access-logfile -
