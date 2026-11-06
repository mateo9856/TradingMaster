"""Private monitoring configuration, durable evaluations and alert episodes."""

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)

from app.helpers.time import utc_now_naive
from app.models.database import Base
from app.models.trading import new_id
from app.models.user import User


class MonitoringSettings(Base):
    __tablename__ = "monitoring_settings"
    user_id = Column(User.__table__.c.id.type, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=False)
    upward_percent = Column(Numeric(8, 4), nullable=False, default=10)
    downward_percent = Column(Numeric(8, 4), nullable=False, default=10)
    check_minutes = Column(Integer, nullable=False, default=60)
    horizon_days = Column(Integer, nullable=False, default=1)
    revision = Column(Integer, nullable=False, default=0)
    next_check_at = Column(DateTime, nullable=False, default=utc_now_naive, index=True)
    lease_token = Column(String(36), nullable=True)
    lease_until = Column(DateTime, nullable=True)
    __table_args__ = (
        CheckConstraint("upward_percent > 0 AND upward_percent <= 100 AND downward_percent > 0 AND downward_percent <= 100", name="thresholds"),
        CheckConstraint("check_minutes IN (15, 60, 1440) AND horizon_days BETWEEN 1 AND 365", name="schedule"),
    )


class MonitoringTarget(Base):
    __tablename__ = "monitoring_targets"
    id = Column(String(36), primary_key=True, default=new_id)
    user_id = Column(User.__table__.c.id.type, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String(160), nullable=False)
    exchange = Column(String(64), nullable=False)
    ticker = Column(String(40), nullable=False)
    trade_id = Column(String(36), ForeignKey("trading_trades.id", ondelete="CASCADE"), nullable=True)
    reference_price = Column(Numeric(28, 8), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now_naive)
    active = Column(Boolean, nullable=False, default=True)
    state = Column(JSON, nullable=False, default=dict)
    result = Column(JSON, nullable=False, default=dict)
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_monitoring_user_target"),)


class MonitoringAlert(Base):
    __tablename__ = "monitoring_alerts"
    id = Column(String(36), primary_key=True, default=new_id)
    user_id = Column(User.__table__.c.id.type, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # Snapshot survives watch removal, so deliberately no target foreign key.
    target_id = Column(String(36), nullable=False)
    kind = Column(String(16), nullable=False)
    direction = Column(String(4), nullable=False)
    episode = Column(Integer, nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now_naive, index=True)
    read_at = Column(DateTime, nullable=True)
    __table_args__ = (UniqueConstraint("target_id", "kind", "direction", "episode", name="uq_monitoring_alert_episode"),)


class MonitoringHistoryEvent(Base):
    """Known split boundaries: forecasts use only the current share denomination."""
    __tablename__ = "monitoring_history_events"
    exchange = Column(String(64), primary_key=True)
    ticker = Column(String(40), primary_key=True)
    timestamp = Column(DateTime, primary_key=True)
