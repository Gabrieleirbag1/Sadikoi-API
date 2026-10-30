"""users.skip_device_verification: store review account that logs in without the emailed device code

Revision ID: 0006_review_account
Revises: 0005_group_notification_settings
Create Date: 2026-10-30 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0006_review_account'
down_revision = '0005_group_notification_settings'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('skip_device_verification', sa.Boolean(), server_default=sa.text('0'), nullable=False))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('skip_device_verification')
