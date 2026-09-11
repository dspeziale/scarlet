from app.deployment.domain import ActualApplicationState, DesiredApplicationState, compute_drift
from app.models.enums import ApplicationState, DesiredState, DriftType


def desired(version="2.5.0", state=DesiredState.RUNNING, replicas=1):
    return DesiredApplicationState(
        application_code="customer-api", version=version, state=state, replicas=replicas
    )


def actual(version="2.5.0", state=ApplicationState.RUNNING, replicas=1):
    return ActualApplicationState(
        application_code="customer-api", version=version, state=state, replicas=replicas
    )


def test_no_drift_when_in_sync():
    report = compute_drift(desired(), actual())
    assert not report.detected and report.drift_type == DriftType.NONE


def test_version_drift():
    report = compute_drift(desired("2.5.0"), actual("2.4.1"))
    assert report.detected and report.drift_type == DriftType.VERSION
    assert (
        report.details["desired_version"] == "2.5.0" and report.details["actual_version"] == "2.4.1"
    )


def test_unexpected_stop():
    report = compute_drift(desired(), actual(state=ApplicationState.STOPPED))
    assert report.detected and report.drift_type == DriftType.UNEXPECTED_STOP


def test_desired_stopped_but_running():
    report = compute_drift(
        desired(state=DesiredState.STOPPED), actual(state=ApplicationState.RUNNING)
    )
    assert report.detected and report.drift_type == DriftType.STATE


def test_missing_container():
    report = compute_drift(desired(), actual(version=None, state=ApplicationState.NOT_INSTALLED))
    assert report.detected and report.drift_type == DriftType.MISSING


def test_unknown_state_is_not_drift():
    report = compute_drift(desired(), actual(version=None, state=ApplicationState.UNKNOWN))
    assert not report.detected


def test_replica_drift():
    report = compute_drift(desired(replicas=3), actual(replicas=1))
    assert report.detected and report.drift_type == DriftType.STATE


def test_absent_desired():
    assert not compute_drift(
        desired(state=DesiredState.ABSENT), actual(state=ApplicationState.NOT_INSTALLED)
    ).detected
    assert compute_drift(
        desired(state=DesiredState.ABSENT), actual(state=ApplicationState.RUNNING)
    ).detected


def test_desired_state_serialization_hides_environment_values():
    d = DesiredApplicationState(
        application_code="a", version="1.0.0", environment={"DB_PASSWORD": "secret"}
    )
    data = d.to_dict()
    assert "environment" not in data
    assert data["environment_keys"] == ["DB_PASSWORD"]
    assert "secret" not in str(data)
