"""question_feedback: likes / dislikes given to the questions served to the groups

Revision ID: 0008_question_feedback
Revises: 0007_chat_message_client_id
Create Date: 2026-11-01 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0008_question_feedback'
down_revision = '0007_chat_message_client_id'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'question_feedback',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('question_id', sa.Integer(), nullable=False),
        sa.Column('liked', sa.Boolean(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['question_id'], ['questions.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'question_id', name='uq_question_feedback_user_question'),
    )


def downgrade():
    op.drop_table('question_feedback')
