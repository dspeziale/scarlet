"""Deployment state machine.

Transitions are explicit; any attempt to move a deployment along an edge that
is not listed raises ``InvalidStateTransitionError``. Terminal states have no
outgoing edges (except ROLLBACK_REQUIRED -> ROLLING_BACK).
"""

from __future__ import annotations

from app.errors import InvalidStateTransitionError
from app.models.enums import DeploymentStatus as S

TRANSITIONS: dict[S, frozenset[S]] = {
    S.CREATED: frozenset(
        {S.PENDING_APPROVAL, S.QUEUED, S.CANCELLED, S.PREFLIGHT_FAILED, S.REJECTED}
    ),
    S.PENDING_APPROVAL: frozenset({S.APPROVED, S.REJECTED, S.CANCELLED}),
    S.APPROVED: frozenset({S.QUEUED, S.CANCELLED}),
    S.QUEUED: frozenset({S.VALIDATING, S.CANCELLED, S.FAILED}),
    S.VALIDATING: frozenset({S.VALIDATED, S.VALIDATION_FAILED, S.FAILED, S.CANCELLED}),
    S.VALIDATED: frozenset({S.PREFLIGHT, S.TRANSFERRING, S.FAILED, S.CANCELLED}),
    # INSTALLING is reachable directly: a cluster target has nothing to transfer,
    # so its plan goes from the checks straight to applying the objects.
    S.PREFLIGHT: frozenset(
        {S.TRANSFERRING, S.INSTALLING, S.PREFLIGHT_FAILED, S.FAILED, S.CANCELLED}
    ),
    S.TRANSFERRING: frozenset({S.TRANSFERRED, S.TRANSFER_FAILED, S.FAILED}),
    S.TRANSFERRED: frozenset({S.INSTALLING, S.FAILED}),
    S.INSTALLING: frozenset({S.INSTALLED, S.INSTALL_FAILED, S.FAILED}),
    S.INSTALLED: frozenset({S.STARTING, S.FAILED, S.ROLLBACK_REQUIRED}),
    S.STARTING: frozenset({S.STARTED, S.START_FAILED, S.ROLLBACK_REQUIRED, S.FAILED}),
    S.STARTED: frozenset({S.HEALTH_CHECKING, S.SUCCESS, S.FAILED}),
    S.HEALTH_CHECKING: frozenset({S.SUCCESS, S.HEALTH_CHECK_FAILED, S.ROLLBACK_REQUIRED, S.FAILED}),
    S.ROLLBACK_REQUIRED: frozenset({S.ROLLING_BACK, S.FAILED}),
    S.ROLLING_BACK: frozenset({S.ROLLED_BACK, S.FAILED}),
    # terminal
    S.SUCCESS: frozenset(),
    S.VALIDATION_FAILED: frozenset(),
    S.PREFLIGHT_FAILED: frozenset(),
    S.TRANSFER_FAILED: frozenset(),
    S.INSTALL_FAILED: frozenset(),
    S.START_FAILED: frozenset(),
    S.HEALTH_CHECK_FAILED: frozenset(),
    S.ROLLED_BACK: frozenset(),
    S.FAILED: frozenset(),
    S.CANCELLED: frozenset(),
    S.REJECTED: frozenset(),
}

# Which failure state corresponds to a failure while in a given running state.
FAILURE_FOR: dict[S, S] = {
    S.VALIDATING: S.VALIDATION_FAILED,
    S.PREFLIGHT: S.PREFLIGHT_FAILED,
    S.TRANSFERRING: S.TRANSFER_FAILED,
    S.INSTALLING: S.INSTALL_FAILED,
    S.STARTING: S.START_FAILED,
    S.HEALTH_CHECKING: S.HEALTH_CHECK_FAILED,
}


def can_transition(current: S | str, target: S | str) -> bool:
    cur = S(current)
    tgt = S(target)
    return tgt in TRANSITIONS.get(cur, frozenset())


def assert_transition(current: S | str, target: S | str) -> S:
    if not can_transition(current, target):
        raise InvalidStateTransitionError(
            f"Cannot move deployment from {S(current).value} to {S(target).value}.",
            details={"from": S(current).value, "to": S(target).value},
        )
    return S(target)


def failure_state_for(current: S | str) -> S:
    return FAILURE_FOR.get(S(current), S.FAILED)


class DeploymentStateMachine:
    """Small helper bound to a deployment model instance."""

    def __init__(self, deployment) -> None:
        self.deployment = deployment

    @property
    def state(self) -> S:
        return S(self.deployment.status)

    def transition(self, target: S | str) -> S:
        new_state = assert_transition(self.state, target)
        self.deployment.status = new_state.value
        return new_state

    def fail(self, *, code: str | None = None, message: str | None = None) -> S:
        target = failure_state_for(self.state)
        if not can_transition(self.state, target):
            target = S.FAILED if can_transition(self.state, S.FAILED) else self.state
        self.deployment.status = target.value
        if code:
            self.deployment.error_code = code
        if message:
            self.deployment.error_message = message
        return target

    @property
    def is_terminal(self) -> bool:
        return self.state.is_terminal
