"""Application configuration."""

import os

# Path to the SQLite database file
DATABASE: str = os.environ.get("DATABASE_PATH", "app.db")

# API key for protecting routes (set via env var in production)
API_KEY: str = os.environ.get("API_KEY", "dev-secret-key")

# Flask settings
DEBUG: bool = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
HOST: str = os.environ.get("FLASK_HOST", "0.0.0.0")
PORT: int = int(os.environ.get("FLASK_PORT", "5000"))
