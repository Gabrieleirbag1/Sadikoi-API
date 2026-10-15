"""bug report status (+ report_users references missing from old databases)

Revision ID: 0002_bug_report_status
Revises: 0001_initial
Create Date: 2026-10-15 13:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0002_bug_report_status'
down_revision = '0001_initial'
branch_labels = None
depends_on = None


def add_missing_columns(table: str, columns: list[sa.Column], foreign_keys: dict[str, tuple[str, str]] | None = None):
    """Databases from before migrations were stamped as 0001_initial whatever their exact columns
    (some already had these, patched by hand): only add what is missing."""
    existing = {column['name'] for column in sa.inspect(op.get_bind()).get_columns(table)}
    missing = [column for column in columns if column.name not in existing]
    if not missing:
        return
    with op.batch_alter_table(table, schema=None) as batch_op:
        for column in missing:
            batch_op.add_column(column)
            if column.name in (foreign_keys or {}):
                target, name = foreign_keys[column.name]
                batch_op.create_foreign_key(name, target, [column.name], ['id'])


def upgrade():
    add_missing_columns('bug_reports', [
        sa.Column('status', sa.String(length=20), server_default='open', nullable=False),
    ])
    add_missing_columns('report_users', [
        sa.Column('group_id', sa.Integer(), nullable=True),
        sa.Column('message_id', sa.Integer(), nullable=True),
    ], foreign_keys={
        'group_id': ('groups', 'fk_report_users_group_id'),
        'message_id': ('chat_messages', 'fk_report_users_message_id'),
    })


def downgrade():
    with op.batch_alter_table('bug_reports', schema=None) as batch_op:
        batch_op.drop_column('status')
