"""Authentication and authorisation boundary — DEVELOPMENT ONLY.

WHAT THIS IS
------------
A real boundary in the right architectural position: every request is authenticated,
then authorised against a permission, before any policy or automation runs. The
*shape* is what a production system needs; the *mechanism* is a development stub.

**Development authentication only.** Production requires integration with an
enterprise identity provider — Entra ID, Okta, or whatever the customer environment
mandates — issuing verified tokens whose claims map to these roles. Nothing here
verifies a signature, checks an expiry, or contacts an issuer.

There are no real credentials in this file. The dev tokens below grant access to a
local prototype driving an in-memory simulator or a local page; they protect nothing.
They exist so that unauthorised and forbidden paths are *testable*, which is the point.
"""
from __future__ import annotations

from dataclasses import dataclass

# Permissions, named for the action rather than the endpoint.
INSPECT_EXECUTIONS = "executions:inspect"
PREPARE_AUTOMATION = "automation:prepare"
CONFIRM_AUTOMATION = "automation:confirm"
INSPECT_AUDIT = "audit:inspect"

ROLE_OPERATOR = "operator"
ROLE_REVIEWER = "reviewer"
ROLE_ADMIN = "admin"

# An operator may prepare but NOT confirm. That is the human-review checkpoint
# expressed as an authorisation rule rather than only as a UI convention: the person
# who stages an action is not automatically the person who approves it.
ROLE_PERMISSIONS: dict[str, set[str]] = {
    ROLE_OPERATOR: {INSPECT_EXECUTIONS, PREPARE_AUTOMATION},
    ROLE_REVIEWER: {INSPECT_EXECUTIONS, PREPARE_AUTOMATION, CONFIRM_AUTOMATION},
    ROLE_ADMIN: {INSPECT_EXECUTIONS, PREPARE_AUTOMATION, CONFIRM_AUTOMATION, INSPECT_AUDIT},
}

# Development principals. Not secrets — see module docstring.
DEV_TOKENS: dict[str, tuple[str, str]] = {
    "dev-operator-token": ("u_operator", ROLE_OPERATOR),
    "dev-reviewer-token": ("u_reviewer", ROLE_REVIEWER),
    "dev-admin-token": ("u_admin", ROLE_ADMIN),
}


@dataclass(frozen=True)
class Actor:
    user_id: str
    role: str

    @property
    def permissions(self) -> set[str]:
        return ROLE_PERMISSIONS.get(self.role, set())

    def can(self, permission: str) -> bool:
        return permission in self.permissions


class AuthenticationError(Exception):
    """No valid principal could be established. -> 401."""


class AuthorizationError(Exception):
    """Valid principal, insufficient permission. -> 403."""

    def __init__(self, message: str, permission: str):
        super().__init__(message)
        self.permission = permission


def authenticate(authorization_header: str | None) -> Actor:
    """Resolve a principal from an Authorization header.

    The header value is never logged or echoed — only the resolved `user_id`.
    """
    if not authorization_header:
        raise AuthenticationError("missing Authorization header")
    value = authorization_header.strip()
    if value.lower().startswith("bearer "):
        value = value[7:].strip()
    entry = DEV_TOKENS.get(value)
    if entry is None:
        # Deliberately does not say whether the token was malformed or simply unknown.
        raise AuthenticationError("invalid credential")
    user_id, role = entry
    return Actor(user_id=user_id, role=role)


def authorize(actor: Actor, permission: str) -> None:
    if not actor.can(permission):
        raise AuthorizationError(
            f"role {actor.role!r} lacks permission {permission!r}", permission)
