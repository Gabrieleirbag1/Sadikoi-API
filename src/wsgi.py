"""Entry point for Gunicorn (the dev server in app.py is only for local use).

Run with exactly ONE worker: the rate limits (Flask-Limiter), the Socket.IO rooms and the
push notification scheduler all live in this process's memory.
    gunicorn -w 1 --threads 100 -b 0.0.0.0:8082 --chdir src wsgi:app
"""
import os

from app import app, main

# Run as `python src/app.py`, Flask's instance folder is <repo>/instance (the Docker volume);
# imported by Gunicorn, it would default to src/instance and silently create an empty database.
app.instance_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'instance')

main()
