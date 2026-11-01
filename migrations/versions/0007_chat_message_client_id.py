"""chat_messages.client_id: id picked by the app for each message, so a message sent twice is stored once

Revision ID: 0007_chat_message_client_id
Revises: 0006_review_account
Create Date: 2026-11-01 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0007_chat_message_client_id'
down_revision = '0006_review_account'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('chat_messages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('client_id', sa.String(length=64), nullable=True))
        batch_op.create_unique_constraint('uq_chat_messages_user_client_id', ['user_id', 'client_id'])


def downgrade():
    with op.batch_alter_table('chat_messages', schema=None) as batch_op:
        batch_op.drop_constraint('uq_chat_messages_user_client_id', type_='unique')
        batch_op.drop_column('client_id')
