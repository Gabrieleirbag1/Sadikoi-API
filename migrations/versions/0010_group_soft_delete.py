"""groups.deleted: deleting a group only marks it, its data stays in the database

Revision ID: 0010_group_soft_delete
Revises: 0009_feedback_categories
Create Date: 2026-11-03 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0010_group_soft_delete'
down_revision = '0009_feedback_categories'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('groups', schema=None) as batch_op:
        batch_op.add_column(sa.Column('deleted', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade():
    with op.batch_alter_table('groups', schema=None) as batch_op:
        batch_op.drop_column('deleted')
