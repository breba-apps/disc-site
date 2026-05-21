import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class BrebaContext:
    request_id: str | None = None
    user_id: str | None = None
    product_id: str | None = None


_context_var: ContextVar[BrebaContext] = ContextVar("breba_context", default=BrebaContext())


def get_context() -> BrebaContext:
    return _context_var.get()


def init_context(
    *,
    request_id: str | None = None,
    user_id: str | None = None,
    product_id: str | None = None,
) -> None:
    """Set a fresh BrebaContext for the current asyncio task. Discards any prior context.
    If request_id is not provided, a fresh uuid is generated."""
    _context_var.set(BrebaContext(
        request_id=request_id or uuid.uuid4().hex,
        user_id=user_id,
        product_id=product_id,
    ))


@contextmanager
def bind_context(
    *,
    request_id: str | None = None,
    user_id: str | None = None,
    product_id: str | None = None,
):
    """Replace the BrebaContext for the duration of the block, then restore the previous one.
    If request_id is not provided, a fresh uuid is generated."""
    token = _context_var.set(BrebaContext(
        request_id=request_id or uuid.uuid4().hex,
        user_id=user_id,
        product_id=product_id,
    ))
    try:
        yield
    finally:
        _context_var.reset(token)
