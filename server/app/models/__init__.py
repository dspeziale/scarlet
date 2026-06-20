"""Model registry — import all models so Alembic can discover them."""

from app.models.base import BaseModel  # noqa: F401
from app.models.tenant import Tenant  # noqa: F401
from app.models.user import User, Role, Permission, RolePermission, UserRole  # noqa: F401
from app.models.probe import Probe, ProbeRegistrationToken, ProbeKey  # noqa: F401
from app.models.task import Task, TaskAssignment, TaskResult  # noqa: F401
from app.models.telemetry import (  # noqa: F401
    DeviceInventory,
    ServiceInventory,
    WifiInventory,
    BLEInventory,
    UsageAccounting,
)
from app.models.ids import IdsAlert, IdsRule, ProbeRuleAssignment  # noqa: F401
from app.models.audit import AuditLog  # noqa: F401
from app.models.token_blocklist import TokenBlocklist  # noqa: F401
