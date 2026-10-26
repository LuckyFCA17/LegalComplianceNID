import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
# Load the app once in the master so DB init / seeding / admin bootstrap run a single time.
preload_app = True
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
threads = 4
timeout = 120  # JDIH sync requests can be slow
accesslog = "-"
