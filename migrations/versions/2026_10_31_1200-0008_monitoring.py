"""Add private monitoring and persistent alert episodes."""

import sqlalchemy as sa
from alembic import op
from fastapi_users_db_sqlalchemy.generics import GUID

revision = "0008_monitoring"
down_revision = "0007_simulated_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('monitoring_settings',
    sa.Column('user_id', GUID(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('upward_percent', sa.Numeric(precision=8, scale=4), nullable=False),
    sa.Column('downward_percent', sa.Numeric(precision=8, scale=4), nullable=False),
    sa.Column('check_minutes', sa.Integer(), nullable=False),
    sa.Column('horizon_days', sa.Integer(), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('next_check_at', sa.DateTime(), nullable=False),
    sa.Column('lease_token', sa.String(length=36), nullable=True),
    sa.Column('lease_until', sa.DateTime(), nullable=True),
    sa.CheckConstraint('check_minutes IN (15, 60, 1440) AND horizon_days BETWEEN 1 AND 365', name=op.f('monitoring_settings_schedule_check')),
    sa.CheckConstraint('upward_percent > 0 AND upward_percent <= 100 AND downward_percent > 0 AND downward_percent <= 100', name=op.f('monitoring_settings_thresholds_check')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('monitoring_settings_user_id_fkey'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('monitoring_settings_pkey'))
    )
    op.create_index(op.f('ix_monitoring_settings_next_check_at'), 'monitoring_settings', ['next_check_at'], unique=False)
    op.create_table('monitoring_targets',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', GUID(), nullable=False),
    sa.Column('key', sa.String(length=160), nullable=False),
    sa.Column('exchange', sa.String(length=64), nullable=False),
    sa.Column('ticker', sa.String(length=40), nullable=False),
    sa.Column('trade_id', sa.String(length=36), nullable=True),
    sa.Column('reference_price', sa.Numeric(precision=28, scale=8), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('state', sa.JSON(), nullable=False),
    sa.Column('result', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['trade_id'], ['trading_trades.id'], name=op.f('monitoring_targets_trade_id_fkey'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('monitoring_targets_user_id_fkey'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('monitoring_targets_pkey')),
    sa.UniqueConstraint('user_id', 'key', name='uq_monitoring_user_target')
    )
    op.create_index(op.f('ix_monitoring_targets_user_id'), 'monitoring_targets', ['user_id'], unique=False)
    op.create_table('monitoring_alerts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', GUID(), nullable=False),
    sa.Column('target_id', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('direction', sa.String(length=4), nullable=False),
    sa.Column('episode', sa.Integer(), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('read_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('monitoring_alerts_user_id_fkey'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('monitoring_alerts_pkey')),
    sa.UniqueConstraint('target_id', 'kind', 'direction', 'episode', name='uq_monitoring_alert_episode')
    )
    op.create_index(op.f('ix_monitoring_alerts_user_id'), 'monitoring_alerts', ['user_id'], unique=False)
    op.create_index(op.f('ix_monitoring_alerts_created_at'), 'monitoring_alerts', ['created_at'], unique=False)
    op.create_table('monitoring_history_events',
    sa.Column('exchange', sa.String(length=64), nullable=False),
    sa.Column('ticker', sa.String(length=40), nullable=False),
    sa.Column('timestamp', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('exchange', 'ticker', 'timestamp', name=op.f('monitoring_history_events_pkey'))
    )

def downgrade() -> None:
    op.drop_table('monitoring_history_events')
    op.drop_table('monitoring_alerts')
    op.drop_table('monitoring_targets')
    op.drop_table('monitoring_settings')
