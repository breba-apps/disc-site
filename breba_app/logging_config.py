import logging
import os

from pythonjsonlogger.json import JsonFormatter

from breba_app.context import get_context

_TEXT_FORMAT = (
    "%(asctime)s %(levelname)s %(name)s "
    "[req=%(request_id)s user=%(user_id)s product=%(product_id)s] %(message)s"
)
_JSON_FIELDS = (
    "%(asctime)s %(levelname)s %(name)s %(message)s "
    "%(request_id)s %(user_id)s %(product_id)s"
)


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        ctx = get_context()
        record.request_id = ctx.request_id or "-"
        record.user_id = ctx.user_id or "-"
        record.product_id = ctx.product_id or "-"
        return True


def setup_logging(level: int | str = logging.INFO, fmt: str | None = None) -> None:
    """Configure root logger. fmt is 'text' or 'json'; defaults to LOG_FORMAT env or 'text'."""
    fmt = (fmt or os.getenv("LOG_FORMAT") or "text").lower()

    handler = logging.StreamHandler()
    handler.addFilter(ContextFilter())

    if fmt == "json":
        handler.setFormatter(JsonFormatter(_JSON_FIELDS))
    else:
        handler.setFormatter(logging.Formatter(_TEXT_FORMAT))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
