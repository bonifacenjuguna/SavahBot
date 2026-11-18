"""Notification Centre: Firebase Cloud Messaging push, in-app inbox and Telegram, behind one pipeline."""
from .categories import REGISTRY, Category, register  # noqa: F401
from .service import NotifyError, Notifier, safe_route  # noqa: F401
