"""bug_reports.category and report_users.category: the preset reason picked by the user

Revision ID: 0009_feedback_categories
Revises: 0008_question_feedback
Create Date: 2026-11-03 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0009_feedback_categories'
down_revision = '0008_question_feedback'
branch_labels = None
depends_on = None


def upgrade():
    # Existing rows were free text only: they become "other".
    for table in ('bug_reports', 'report_users'):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column('category', sa.String(length=30), server_default='other', nullable=False))


def downgrade():
    for table in ('bug_reports', 'report_users'):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_column('category')
