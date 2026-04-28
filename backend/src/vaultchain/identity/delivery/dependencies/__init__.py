"""FastAPI dependencies for the identity context — current-user resolution + CSRF guard."""

from vaultchain.identity.delivery.dependencies.csrf import CsrfGuard
from vaultchain.identity.delivery.dependencies.current_user import (
    GetCurrentUser,
    UserContext,
)

__all__ = ["CsrfGuard", "GetCurrentUser", "UserContext"]
