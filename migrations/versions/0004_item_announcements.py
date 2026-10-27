"""item announcements: what happened to the previous question's item, shown after each daily reset

Revision ID: 0004_item_announcements
Revises: 0003_push_notifications
Create Date: 2026-10-27 19:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0004_item_announcements'
down_revision = '0003_push_notifications'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('item_announcements',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('question_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('item_name', sa.String(length=100), nullable=False),
    sa.Column('from_user_id', sa.Integer(), nullable=True),
    sa.Column('streak', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['from_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['question_id'], ['questions.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('question_id')
    )


def downgrade():
    op.drop_table('item_announcements')
