"""notification settings per group (one switch per type instead of notifications_muted) and the "answers" type

Revision ID: 0005_group_notification_settings
Revises: 0004_item_announcements
Create Date: 2026-10-29 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0005_group_notification_settings'
down_revision = '0004_item_announcements'
branch_labels = None
depends_on = None

GROUP_COLUMNS = ['notify_messages', 'notify_questions', 'notify_vote_reminder', 'notify_answers']


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('notify_answers', sa.Boolean(), server_default=sa.text('1'), nullable=False))

    with op.batch_alter_table('group_user', schema=None) as batch_op:
        for column in GROUP_COLUMNS:
            batch_op.add_column(sa.Column(column, sa.Boolean(), server_default=sa.text('1'), nullable=False))

    # A muted group keeps all its notifications off.
    op.execute(f"UPDATE group_user SET {', '.join(f'{column} = 0' for column in GROUP_COLUMNS)} "
               "WHERE notifications_muted = 1")

    with op.batch_alter_table('group_user', schema=None) as batch_op:
        batch_op.drop_column('notifications_muted')


def downgrade():
    with op.batch_alter_table('group_user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('notifications_muted', sa.Boolean(), server_default=sa.text('0'), nullable=False))

    # Muted again only if every type was off.
    op.execute("UPDATE group_user SET notifications_muted = 1 "
               f"WHERE {' AND '.join(f'{column} = 0' for column in GROUP_COLUMNS)}")

    with op.batch_alter_table('group_user', schema=None) as batch_op:
        for column in reversed(GROUP_COLUMNS):
            batch_op.drop_column(column)

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('notify_answers')
