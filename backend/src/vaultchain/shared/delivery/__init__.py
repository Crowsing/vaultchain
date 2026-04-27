"""Shared HTTP delivery primitives — envelope schema, middleware, exception handlers.

Phase 1 brief `phase1-shared-005` introduces this layer. The composition root
(`vaultchain.main`) wires the middleware and registers the handlers.
"""

from vaultchain.shared.delivery.error_handlers import (
    ErrorEnvelope,
    register_error_handlers,
)
from vaultchain.shared.delivery.middleware import (
    REQUEST_ID_HEADER,
    RequestIdMiddleware,
    get_request_id,
)

__all__ = [
    "REQUEST_ID_HEADER",
    "ErrorEnvelope",
    "RequestIdMiddleware",
    "get_request_id",
    "register_error_handlers",
]
