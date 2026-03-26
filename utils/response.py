"""Structured API response helpers.

All API responses follow the envelope:
    {"success": bool, "data": any, "message": str | None, "errors": any}
"""

from typing import Any, Optional
from flask import jsonify, Response


def success_response(
    data: Any = None,
    message: Optional[str] = None,
    status_code: int = 200,
) -> tuple[Response, int]:
    """Return a successful JSON response.

    Args:
        data: The payload to return under the "data" key.
        message: Optional human-readable message.
        status_code: HTTP status code (default 200).

    Returns:
        A Flask JSON response tuple (response, status_code).
    """
    return jsonify({"success": True, "data": data, "message": message, "errors": None}), status_code


def error_response(
    message: str,
    errors: Any = None,
    status_code: int = 400,
) -> tuple[Response, int]:
    """Return an error JSON response.

    Args:
        message: Human-readable description of the error.
        errors: Optional structured error details (dict, list, etc.).
        status_code: HTTP status code (default 400).

    Returns:
        A Flask JSON response tuple (response, status_code).
    """
    return jsonify({"success": False, "data": None, "message": message, "errors": errors}), status_code
