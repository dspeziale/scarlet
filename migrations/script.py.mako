"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

Regola aziendale (docs/DEPLOYMENT.md): ogni migrazione deve essere retro-compatibile con la
versione precedente del codice (expand/contract), cosi' il rollback applicativo non richiede
il downgrade dello schema.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
