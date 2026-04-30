#!/usr/bin/env python3
"""
serve.py  –  VolunteerHub development server
=============================================
Starts the Flask application for local development.

Usage
-----
  python serve.py                     # default: http://localhost:5000
  python serve.py --port 8080
  python serve.py --host 0.0.0.0     # listen on all interfaces
  python serve.py --no-debug          # disable auto-reload

Environment
-----------
Copy .env.example to .env and set DATABASE_URL, SECRET_KEY, etc.
If DATABASE_URL is not set, defaults to SQLite (volunteer_manager.db in the cwd).
"""

from __future__ import annotations

import argparse
from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    parser = argparse.ArgumentParser(description="VolunteerHub development server")
    parser.add_argument("--host",     default="127.0.0.1")
    parser.add_argument("--port",     default=5000, type=int)
    parser.add_argument("--no-debug", action="store_true")
    args = parser.parse_args()

    from volunteer_manager import create_app
    app = create_app()

    print(f"\n  VolunteerHub running at  http://{args.host}:{args.port}/\n")
    app.run(
        host=args.host,
        port=args.port,
        debug=not args.no_debug,
        use_reloader=not args.no_debug,
    )


if __name__ == "__main__":
    main()
