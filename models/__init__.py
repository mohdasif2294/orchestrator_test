"""Shared database utilities for the models layer."""

import sqlite3
import config


def get_conn() -> sqlite3.Connection:
    """Return a configured SQLite connection with Row factory and FK enforcement.

    Returns:
        An open sqlite3.Connection. Caller is responsible for closing it.
    """
    conn = sqlite3.connect(config.DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
