"""user_blocks: a user blocking another one hides their messages from each other's chat

Revision ID: 0012_user_blocks
Revises: 0011_group_user_left_at
Create Date: 2026-11-27 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0012_user_blocks'
down_revision = '0011_group_user_left_at'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'user_blocks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('blocker_id', sa.Integer(), nullable=False),
        sa.Column('blocked_id', sa.Integer(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['blocked_id'], ['users.id']),
        sa.ForeignKeyConstraint(['blocker_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('blocker_id', 'blocked_id', name='uq_user_blocks_pair'),
    )


def downgrade():
    op.drop_table('user_blocks')
