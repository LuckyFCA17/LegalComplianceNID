import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
# Load the app once in the master so DB init / seeding / admin bootstrap run a single time.
preload_app = True
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
threads = 4
timeout = 600  # a JDIH sync opens many pages (search, detail, PDF lookup)
accesslog = "-"
