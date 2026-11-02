"""add reservation conflict index

Revision ID: 599991e83353
Revises: 5ce161a3c16f
Create Date: 2026-11-02 18:48:28.167588

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '599991e83353'
down_revision: Union[str, Sequence[str], None] = '5ce161a3c16f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Some legacy databases were created after the index was added to the ORM.
    # Accept either legacy state without creating a duplicate index.
    if not op.get_context().as_sql:
        indexes = sa.inspect(op.get_bind()).get_indexes('reservations')
        if any(index['name'] == 'ix_reservations_conflict_lookup' for index in indexes):
            return
    op.create_index(
        'ix_reservations_conflict_lookup', 'reservations',
        ['lab_id', 'date', 'status', 'start_time', 'end_time'], unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_reservations_conflict_lookup', table_name='reservations')
