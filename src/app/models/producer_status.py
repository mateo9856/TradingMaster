"""Shared heartbeat and duplicate-start count for the singleton Kafka producer."""

from sqlalchemy import Column, DateTime, Integer, String

from app.models.database import Base


class ProducerStatus(Base):
    __tablename__ = "producer_status"

    id = Column(Integer, primary_key=True)
    instance_id = Column(String(36), nullable=True)
    started_at = Column(DateTime, nullable=True)
    heartbeat_at = Column(DateTime, nullable=True)
    duplicate_starts = Column(Integer, nullable=False, default=0, server_default="0")
