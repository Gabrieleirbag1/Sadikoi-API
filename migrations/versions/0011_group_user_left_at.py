"""group_user.left_at: leaving a group only marks the membership, the row stays in the database

Revision ID: 0011_group_user_left_at
Revises: 0010_group_soft_delete
Create Date: 2026-11-03 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0011_group_user_left_at'
down_revision = '0010_group_soft_delete'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('group_user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('left_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    # Before this column, leaving a group deleted the row.
    op.execute("DELETE FROM group_user WHERE left_at IS NOT NULL")
    with op.batch_alter_table('group_user', schema=None) as batch_op:
        batch_op.drop_column('left_at')
