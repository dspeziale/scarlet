"""WSGI entry point — compatible with Gunicorn and Vercel."""

import os
import sys

# When Vercel deploys from the repo root, 'server/' may not be on sys.path.
# This ensures 'app' package and 'config' module resolve correctly.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app  # noqa: E402

application = create_app()
app = application          # Vercel requires a top-level name: 'app' or 'application'

if __name__ == "__main__":
    application.run(host="0.0.0.0", port=5000, debug=True)
