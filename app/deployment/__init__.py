"""Deployment engine: manifest contract, package validation, storage, planning and execution."""

from app.deployment.domain import (
    ActualApplicationState,
    DeploymentExecution,
    DeploymentPlan,
    DesiredApplicationState,
    DriftReport,
    HealthSpec,
    PlanStep,
    StepExecution,
    compute_drift,
)
from app.deployment.manifest import Manifest, parse_manifest
from app.deployment.remote_layout import RemoteLayout
from app.deployment.state_machine import DeploymentStateMachine, assert_transition, can_transition
from app.deployment.storage import ArtifactStorage, LocalFilesystemArtifactStorage, get_artifact_storage
from app.deployment.validator import PackageValidator, ValidationReport, safe_extract

__all__ = [
    "ActualApplicationState",
    "ArtifactStorage",
    "DeploymentExecution",
    "DeploymentPlan",
    "DeploymentStateMachine",
    "DesiredApplicationState",
    "DriftReport",
    "HealthSpec",
    "LocalFilesystemArtifactStorage",
    "Manifest",
    "PackageValidator",
    "PlanStep",
    "RemoteLayout",
    "StepExecution",
    "ValidationReport",
    "assert_transition",
    "can_transition",
    "compute_drift",
    "get_artifact_storage",
    "parse_manifest",
    "safe_extract",
]
