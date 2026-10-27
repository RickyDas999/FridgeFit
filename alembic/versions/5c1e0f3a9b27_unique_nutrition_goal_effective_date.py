"""Unique nutrition goal effective date: one goal may start on a given date.

Fails, and changes nothing, if a database already has two goals starting on the same date;
those must be resolved by hand first. No data is deleted here.

Revision ID: 5c1e0f3a9b27
Revises: d22b106d0d3b
Create Date: 2026-10-27 12:00:00.000000
"""

from alembic import op

revision: str = "5c1e0f3a9b27"
down_revision: str | None = "d22b106d0d3b"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add the unique constraint on ``nutrition_goals.effective_date``."""
    # Batch mode: SQLite cannot add a constraint in place, so the table is recreated there.
    with op.batch_alter_table("nutrition_goals") as batch_op:
        batch_op.create_unique_constraint(
            op.f("uq_nutrition_goals_effective_date"), ["effective_date"]
        )


def downgrade() -> None:
    """Drop the unique constraint on ``nutrition_goals.effective_date``."""
    with op.batch_alter_table("nutrition_goals") as batch_op:
        batch_op.drop_constraint(op.f("uq_nutrition_goals_effective_date"), type_="unique")
