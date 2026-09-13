import pytest

from app.deployment.state_machine import (
    TRANSITIONS,
    DeploymentStateMachine,
    assert_transition,
    can_transition,
    failure_state_for,
)
from app.errors import InvalidStateTransitionError
from app.models.enums import TERMINAL_DEPLOYMENT_STATES
from app.models.enums import DeploymentStatus as S


class Dep:
    def __init__(self, status):
        self.status = status
        self.error_code = None
        self.error_message = None


def test_happy_path():
    dep = Dep(S.CREATED.value)
    sm = DeploymentStateMachine(dep)
    for target in (
        S.QUEUED,
        S.VALIDATING,
        S.VALIDATED,
        S.PREFLIGHT,
        S.TRANSFERRING,
        S.TRANSFERRED,
        S.INSTALLING,
        S.INSTALLED,
        S.STARTING,
        S.STARTED,
        S.HEALTH_CHECKING,
        S.SUCCESS,
    ):
        sm.transition(target)
    assert sm.is_terminal
    assert S(dep.status).summary == "SUCCESS"


def test_invalid_transition_raises():
    with pytest.raises(InvalidStateTransitionError):
        assert_transition(S.CREATED, S.SUCCESS)
    with pytest.raises(InvalidStateTransitionError):
        assert_transition(S.SUCCESS, S.QUEUED)
    assert not can_transition(S.FAILED, S.RUNNING if hasattr(S, "RUNNING") else S.QUEUED)


def test_terminal_states_have_no_outgoing_edges():
    for state in TERMINAL_DEPLOYMENT_STATES - {
        S.ROLLBACK_REQUIRED
    }:  # ROLLBACK_REQUIRED -> ROLLING_BACK only within the same run
        assert TRANSITIONS[state] == frozenset(), state
    assert not S.QUEUED.is_terminal
    assert S.ROLLED_BACK.is_terminal


def test_failure_mapping():
    assert failure_state_for(S.TRANSFERRING) == S.TRANSFER_FAILED
    assert failure_state_for(S.HEALTH_CHECKING) == S.HEALTH_CHECK_FAILED
    assert failure_state_for(S.QUEUED) == S.FAILED
    dep = Dep(S.INSTALLING.value)
    DeploymentStateMachine(dep).fail(code="X", message="boom")
    assert dep.status == S.INSTALL_FAILED.value and dep.error_code == "X"


def test_approval_flow():
    dep = Dep(S.CREATED.value)
    sm = DeploymentStateMachine(dep)
    sm.transition(S.PENDING_APPROVAL)
    with pytest.raises(InvalidStateTransitionError):
        sm.transition(S.VALIDATING)
    sm.transition(S.APPROVED)
    sm.transition(S.QUEUED)
    assert S(dep.status).summary == "QUEUED"


def test_rollback_flow():
    dep = Dep(S.HEALTH_CHECKING.value)
    sm = DeploymentStateMachine(dep)
    sm.transition(S.ROLLBACK_REQUIRED)
    sm.transition(S.ROLLING_BACK)
    sm.transition(S.ROLLED_BACK)
    assert S(dep.status).summary == "ROLLED_BACK"


def test_summaries():
    assert S.PENDING_APPROVAL.summary == "PENDING_APPROVAL"
    assert S.CANCELLED.summary == "CANCELLED"
    assert S.START_FAILED.summary == "FAILED" and S.START_FAILED.is_failure
    assert S.INSTALLING.summary == "RUNNING"


def test_celery_tasks_are_registered(app):
    from app.tasks.celery_app import celery

    names = {n for n in celery.tasks if n.startswith("scarlet.")}
    assert {
        "scarlet.deploy.deploy_application",
        "scarlet.deploy.run_deployment_batch",
        "scarlet.lifecycle.run_operation",
        "scarlet.host.test_ssh_connection",
        "scarlet.host.discover_host",
        "scarlet.maintenance.reconcile",
        "scarlet.maintenance.cleanup",
        "scarlet.maintenance.health_sweep",
    } <= names
