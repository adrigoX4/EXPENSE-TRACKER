"""money history ledger

Revision ID: 7b41f0c2d9aa
Revises: 1d82829431ba
Create Date: 2026-10-26 22:10:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7b41f0c2d9aa"
down_revision: Union[str, None] = "1d82829431ba"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("expenses", schema=None) as batch_op:
        batch_op.add_column(sa.Column("paid_to", sa.String(length=120), nullable=True))

    op.create_table(
        "money_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=80), nullable=True),
        sa.Column(
            "direction",
            sa.Enum(
                "in",
                "out",
                name="money_direction",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("person", sa.String(length=120), nullable=True),
        sa.Column("category", sa.String(length=60), nullable=False),
        sa.Column("method", sa.String(length=40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.Column("reference", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_void", sa.Boolean(), nullable=False),
        sa.Column("void_reason", sa.String(length=300), nullable=True),
        sa.Column("voided_at", sa.DateTime(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_money_transactions_amount_positive"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("money_transactions", schema=None) as batch_op:
        batch_op.create_index("ix_money_transactions_category", ["category"], unique=False)
        batch_op.create_index("ix_money_transactions_direction", ["direction"], unique=False)
        batch_op.create_index(
            "ix_money_transactions_idempotency_key", ["idempotency_key"], unique=True
        )
        batch_op.create_index("ix_money_transactions_method", ["method"], unique=False)
        batch_op.create_index(
            "ix_money_transactions_occurred_at", ["occurred_at"], unique=False
        )
        batch_op.create_index("ix_money_transactions_uuid", ["uuid"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("money_transactions", schema=None) as batch_op:
        batch_op.drop_index("ix_money_transactions_uuid")
        batch_op.drop_index("ix_money_transactions_occurred_at")
        batch_op.drop_index("ix_money_transactions_method")
        batch_op.drop_index("ix_money_transactions_idempotency_key")
        batch_op.drop_index("ix_money_transactions_direction")
        batch_op.drop_index("ix_money_transactions_category")
    op.drop_table("money_transactions")
    with op.batch_alter_table("expenses", schema=None) as batch_op:
        batch_op.drop_column("paid_to")
