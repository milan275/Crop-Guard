"""
CropGuard AI — SQLAlchemy ORM models.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey,
    Integer, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.db import Base


class Farm(Base):
    __tablename__ = "farms"

    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    latitude:   Mapped[float]    = mapped_column(Float, nullable=False)
    longitude:  Mapped[float]    = mapped_column(Float, nullable=False)
    district:   Mapped[Optional[str]] = mapped_column(String(100))
    email:      Mapped[str]      = mapped_column(String(255), nullable=False, index=True)
    crop:       Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    alerts: Mapped[list["Alert"]] = relationship("Alert", back_populates="farm", cascade="all, delete-orphan")


class Override(Base):
    __tablename__ = "overrides"

    id:                  Mapped[int]   = mapped_column(Integer, primary_key=True, autoincrement=True)
    bottom_left_lat:     Mapped[float] = mapped_column(Float, nullable=False)
    bottom_left_lon:     Mapped[float] = mapped_column(Float, nullable=False)
    top_right_lat:       Mapped[float] = mapped_column(Float, nullable=False)
    top_right_lon:       Mapped[float] = mapped_column(Float, nullable=False)
    override_prediction: Mapped[float] = mapped_column(Float, nullable=False)
    override_suggestion: Mapped[Optional[str]] = mapped_column(Text)
    created_at:          Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at:          Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    active:              Mapped[bool]  = mapped_column(Boolean, default=True)


class Alert(Base):
    __tablename__ = "alerts"

    id:               Mapped[int]   = mapped_column(Integer, primary_key=True, autoincrement=True)
    farm_id:          Mapped[int]   = mapped_column(Integer, ForeignKey("farms.id"), nullable=False)
    risk_level:       Mapped[str]   = mapped_column(String(20), nullable=False)
    risk_probability: Mapped[float] = mapped_column(Float, nullable=False)
    message:          Mapped[Optional[str]] = mapped_column(Text)
    sent_at:          Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    alert_type:       Mapped[str]   = mapped_column(String(50), default="risk_threshold")

    farm: Mapped["Farm"] = relationship("Farm", back_populates="alerts")
