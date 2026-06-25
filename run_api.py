#!/usr/bin/env python3
"""Launch the AlphaDesk cockpit API with .env loaded.

Keeps env-loading out of src/api/app.py so importing the app in tests never
mutates the process environment. Run:  python run_api.py
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.api.app:app", host="127.0.0.1", port=8000, log_level="warning")
