"""Authentication helpers.

Provides a simple API-key decorator. The key is read from the
X-API-Key request header and validated against config.API_KEY.

Usage:
    from utils.auth import require_api_key

    @bp.route("/resource", methods=["GET"])
    @require_api_key
    def get_resource():
        ...
"""

import functools
from typing import Callable
from flask import request
from utils.response import error_response
import config


def require_api_key(fn: Callable) -> Callable:
    """Decorator that enforces API key authentication.

    Reads the X-API-Key header and compares it to config.API_KEY.
    Returns 401 if the header is missing or the key does not match.

    Args:
        fn: The route function to protect.

    Returns:
        The wrapped function.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        api_key = request.headers.get("X-API-Key", "")
        if not api_key or api_key != config.API_KEY:
            return error_response("Unauthorized: invalid or missing API key", status_code=401)
        return fn(*args, **kwargs)

    return wrapper
