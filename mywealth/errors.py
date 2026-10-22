"""Domain errors, mapped to HTTP statuses by the server. Messages are shown in the UI (Italian)."""

from __future__ import annotations


class AppError(Exception):
    status = 400


class ValidationError(AppError, ValueError):
    status = 400


class NotFoundError(AppError):
    status = 404


class ConflictError(AppError):
    """The request is valid but clashes with existing data (e.g. deleting a used account)."""

    status = 409
