"""push notifications: preferences (users, group_user), sent-markers (groups) and push_tokens

Revision ID: 0003_push_notifications
Revises: 0002_bug_report_status
Create Date: 2026-10-26 09:51:27.974669

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0003_push_notifications'
down_revision = '0002_bug_report_status'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('push_tokens',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('token', sa.String(length=255), nullable=False),
    sa.Column('device_id', sa.String(length=64), nullable=True),
    sa.Column('platform', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token')
    )
    with op.batch_alter_table('group_user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('notifications_muted', sa.Boolean(), server_default=sa.text('0'), nullable=False))

    with op.batch_alter_table('groups', schema=None) as batch_op:
        batch_op.add_column(sa.Column('last_question_notified_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('last_vote_reminder_at', sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('notify_messages', sa.Boolean(), server_default=sa.text('1'), nullable=False))
        batch_op.add_column(sa.Column('notify_questions', sa.Boolean(), server_default=sa.text('1'), nullable=False))
        batch_op.add_column(sa.Column('notify_vote_reminder', sa.Boolean(), server_default=sa.text('1'), nullable=False))



def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('notify_vote_reminder')
        batch_op.drop_column('notify_questions')
        batch_op.drop_column('notify_messages')

    with op.batch_alter_table('groups', schema=None) as batch_op:
        batch_op.drop_column('last_vote_reminder_at')
        batch_op.drop_column('last_question_notified_at')

    with op.batch_alter_table('group_user', schema=None) as batch_op:
        batch_op.drop_column('notifications_muted')

    op.drop_table('push_tokens')
