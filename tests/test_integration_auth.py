"""The authentication / authorisation boundary (Day-5 integration upgrade).

**Development authentication only.** Nothing here verifies a signature, checks an
expiry or contacts an issuer, and these tests do not pretend otherwise. What they
assert is that the boundary is in the right *architectural position* and that its
decisions are real: a request is authenticated, then authorised against a named
permission, before any automation runs.

The load-bearing rule is that an **operator can prepare but cannot confirm**. That is
the human-review checkpoint expressed as an authorisation rule rather than a UI
convention — the person who stages an action is not automatically the person who
approves it.
"""

from __future__ import annotations

import pytest

from procmine.integrations.auth import (
    CONFIRM_AUTOMATION, DEV_TOKENS, INSPECT_AUDIT, INSPECT_EXECUTIONS,
    PREPARE_AUTOMATION, ROLE_ADMIN, ROLE_OPERATOR, ROLE_PERMISSIONS, ROLE_REVIEWER,
    Actor, AuthenticationError, AuthorizationError, authenticate, authorize,
)


# --- authentication -------------------------------------------------------

@pytest.mark.parametrize("token,user,role", [
    ("dev-operator-token", "u_operator", ROLE_OPERATOR),
    ("dev-reviewer-token", "u_reviewer", ROLE_REVIEWER),
    ("dev-admin-token", "u_admin", ROLE_ADMIN),
])
def test_a_known_development_credential_resolves_to_its_principal(token, user, role):
    actor = authenticate(token)
    assert (actor.user_id, actor.role) == (user, role)


def test_a_bearer_prefix_is_accepted():
    assert authenticate("Bearer dev-admin-token").role == ROLE_ADMIN


def test_the_bearer_prefix_is_case_insensitive_and_whitespace_tolerant():
    assert authenticate("  bearer   dev-admin-token  ").role == ROLE_ADMIN


def test_a_missing_credential_is_rejected():
    for missing in (None, "", "   "):
        with pytest.raises(AuthenticationError):
            authenticate(missing)


def test_an_unknown_credential_is_rejected():
    with pytest.raises(AuthenticationError):
        authenticate("Bearer not-a-real-token")


def test_the_rejection_does_not_say_which_part_was_wrong():
    """Distinguishing 'malformed' from 'unknown' hands an attacker a probe."""
    with pytest.raises(AuthenticationError) as unknown:
        authenticate("Bearer wrong-token")
    with pytest.raises(AuthenticationError) as malformed:
        authenticate("Basic abc123")
    assert str(unknown.value) == str(malformed.value) == "invalid credential"


def test_the_error_never_echoes_the_submitted_credential():
    with pytest.raises(AuthenticationError) as exc:
        authenticate("Bearer super-secret-value")
    assert "super-secret-value" not in str(exc.value)


# --- authorisation --------------------------------------------------------

def test_an_operator_may_prepare():
    authorize(Actor("u_operator", ROLE_OPERATOR), PREPARE_AUTOMATION)


def test_an_operator_may_not_confirm():
    """The human-review checkpoint, expressed as an authorisation rule."""
    with pytest.raises(AuthorizationError) as exc:
        authorize(Actor("u_operator", ROLE_OPERATOR), CONFIRM_AUTOMATION)
    assert exc.value.permission == CONFIRM_AUTOMATION


def test_a_reviewer_may_confirm():
    authorize(Actor("u_reviewer", ROLE_REVIEWER), CONFIRM_AUTOMATION)


def test_only_an_admin_may_read_the_audit_trail():
    authorize(Actor("u_admin", ROLE_ADMIN), INSPECT_AUDIT)
    for role in (ROLE_OPERATOR, ROLE_REVIEWER):
        with pytest.raises(AuthorizationError):
            authorize(Actor("u", role), INSPECT_AUDIT)


def test_every_role_may_inspect_executions():
    for role in (ROLE_OPERATOR, ROLE_REVIEWER, ROLE_ADMIN):
        authorize(Actor("u", role), INSPECT_EXECUTIONS)


def test_an_unknown_role_gets_no_permissions_at_all():
    """Fail closed: an unrecognised role is powerless, not unrestricted."""
    stranger = Actor("u_stranger", "superuser")
    assert stranger.permissions == set()
    for permission in (INSPECT_EXECUTIONS, PREPARE_AUTOMATION, CONFIRM_AUTOMATION,
                       INSPECT_AUDIT):
        with pytest.raises(AuthorizationError):
            authorize(stranger, permission)


def test_the_authorisation_error_names_the_permission_not_the_secret():
    with pytest.raises(AuthorizationError) as exc:
        authorize(Actor("u_operator", ROLE_OPERATOR), CONFIRM_AUTOMATION)
    message = str(exc.value)
    assert CONFIRM_AUTOMATION in message
    assert not any(t in message for t in DEV_TOKENS)


# --- the shape of the model ----------------------------------------------

def test_privileges_are_strictly_nested_operator_reviewer_admin():
    operator = ROLE_PERMISSIONS[ROLE_OPERATOR]
    reviewer = ROLE_PERMISSIONS[ROLE_REVIEWER]
    admin = ROLE_PERMISSIONS[ROLE_ADMIN]
    assert operator < reviewer < admin, "roles must escalate, not diverge"


def test_confirm_is_the_permission_that_separates_operator_from_reviewer():
    assert (ROLE_PERMISSIONS[ROLE_REVIEWER] - ROLE_PERMISSIONS[ROLE_OPERATOR]
            == {CONFIRM_AUTOMATION})


def test_can_agrees_with_authorize():
    for role in (ROLE_OPERATOR, ROLE_REVIEWER, ROLE_ADMIN):
        actor = Actor("u", role)
        for permission in (PREPARE_AUTOMATION, CONFIRM_AUTOMATION, INSPECT_AUDIT):
            allowed = actor.can(permission)
            try:
                authorize(actor, permission)
                assert allowed
            except AuthorizationError:
                assert not allowed


def test_an_actor_is_immutable():
    """A principal that could be edited after authentication is not a principal."""
    with pytest.raises(Exception):
        Actor("u_operator", ROLE_OPERATOR).role = ROLE_ADMIN


def test_the_development_tokens_are_obviously_development_tokens():
    """Guards against a real-looking credential ever being pasted in here."""
    for token in DEV_TOKENS:
        assert token.startswith("dev-"), token
        assert len(token) < 40, token
