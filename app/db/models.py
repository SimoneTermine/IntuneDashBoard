"""
Database models for Intune Dashboard.
Unified model: Control → Assignment → Outcome per device.
v1.2.1: Removed Remediation model (Proactive Remediations feature removed).
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, Text, Float,
    ForeignKey, Index, JSON, create_engine, event
)
from sqlalchemy.orm import DeclarativeBase, relationship, Session
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Device
# ---------------------------------------------------------------------------
class Device(Base):
    """Represents a managed device from Intune."""
    __tablename__ = "devices"

    id = Column(String, primary_key=True)
    device_name = Column(String, index=True)
    serial_number = Column(String, index=True)
    device_type = Column(String)
    operating_system = Column(String)
    os_version = Column(String)
    compliance_state = Column(String, index=True)
    management_state = Column(String)
    ownership = Column(String)
    enrolled_date_time = Column(DateTime)
    last_sync_date_time = Column(DateTime, index=True)
    user_principal_name = Column(String, index=True)
    user_display_name = Column(String)
    user_id = Column(String)
    azure_ad_device_id = Column(String)
    enroll_profile = Column(String)
    model = Column(String)
    manufacturer = Column(String)
    imei = Column(String)
    total_storage_space_in_bytes = Column(Integer)
    free_storage_space_in_bytes = Column(Integer)
    jail_broken = Column(String)
    encrypted = Column(Boolean)
    managed_device_owner_type = Column(String)
    raw_json = Column(Text)
    synced_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    compliance_statuses = relationship("DeviceComplianceStatus", back_populates="device", cascade="all, delete-orphan")
    app_statuses = relationship("DeviceAppStatus", back_populates="device", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Device {self.device_name} ({self.id[:8]}...)>"


# ---------------------------------------------------------------------------
# Control (Policy / App / Script)
# ---------------------------------------------------------------------------
class Control(Base):
    """Unified entity: any Intune object that applies settings/state to devices."""
    __tablename__ = "controls"

    id = Column(String, primary_key=True)
    display_name = Column(String, index=True)
    control_type = Column(String, index=True)
    platform = Column(String)
    description = Column(Text)
    created_datetime = Column(DateTime)
    last_modified_datetime = Column(DateTime)
    version = Column(String)
    is_assigned = Column(Boolean, default=False)
    assignment_count = Column(Integer, default=0)
    api_source = Column(String)
    raw_json = Column(Text)
    synced_at = Column(DateTime, default=func.now())

    assignments = relationship("Assignment", back_populates="control", cascade="all, delete-orphan")
    outcomes = relationship("Outcome", back_populates="control", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Control {self.display_name} ({self.control_type})>"


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------
class Assignment(Base):
    """Represents a Graph assignment: control → group/allDevices."""
    __tablename__ = "assignments"

    id = Column(String, primary_key=True)
    control_id = Column(String, ForeignKey("controls.id", ondelete="CASCADE"), index=True)
    target_type = Column(String)        # group / allDevices / allUsers / configManagerCollection
    target_id = Column(String, index=True)
    target_display_name = Column(String)
    intent = Column(String, default="include")  # include / exclude
    filter_id = Column(String)
    filter_type = Column(String)
    raw_json = Column(Text)
    synced_at = Column(DateTime, default=func.now())

    control = relationship("Control", back_populates="assignments")

    __table_args__ = (
        Index("ix_assignment_control_target", "control_id", "target_id"),
    )


# ---------------------------------------------------------------------------
# Group
# ---------------------------------------------------------------------------
class Group(Base):
    """Entra ID group."""
    __tablename__ = "groups"

    id = Column(String, primary_key=True)
    display_name = Column(String, index=True)
    description = Column(Text)
    group_types = Column(String)
    mail = Column(String)
    membership_rule = Column(Text)
    membership_rule_processing_state = Column(String)
    member_count = Column(Integer)
    raw_json = Column(Text)
    synced_at = Column(DateTime, default=func.now())


# ---------------------------------------------------------------------------
# DeviceGroupMembership
# ---------------------------------------------------------------------------
class DeviceGroupMembership(Base):
    """Many-to-many: device ↔ group."""
    __tablename__ = "device_group_memberships"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String, ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    group_id = Column(String, ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    synced_at = Column(DateTime, default=func.now())

    __table_args__ = (
        Index("ix_dev_grp", "device_id", "group_id"),
    )


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
class App(Base):
    """Managed mobile app from Intune."""
    __tablename__ = "apps"

    id = Column(String, primary_key=True)
    display_name = Column(String, index=True)
    app_type = Column(String)
    publisher = Column(String)
    description = Column(Text)
    version = Column(String)
    last_modified_datetime = Column(DateTime)
    is_assigned = Column(Boolean)
    total_assigned_device_count = Column(Integer)
    total_installed_device_count = Column(Integer)
    failed_device_count = Column(Integer)
    raw_json = Column(Text)
    synced_at = Column(DateTime, default=func.now())

    device_statuses = relationship("DeviceAppStatus", back_populates="app", cascade="all, delete-orphan")


class DeviceAppStatus(Base):
    """Per-device installation status of an app."""
    __tablename__ = "device_app_statuses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(String, ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    app_id = Column(String, ForeignKey("apps.id", ondelete="CASCADE"), index=True)
    install_state = Column(String)
    error_code = Column(Integer)
    last_sync_date_time = Column(DateTime)
    device_name = Column(String)
    user_name = Column(String)
    raw_json = Column(Text)
    synced_at = Column(DateTime, default=func.now())

    device = relationship("Device", back_populates="app_statuses")
    app = relationship("App", back_populates="device_statuses")

    __table_args__ = (
        Index("ix_device_app", "device_id", "app_id"),
    )


# ---------------------------------------------------------------------------
# Snapshot (for drift detection)
# ---------------------------------------------------------------------------
class Snapshot(Base):
    """Point-in-time snapshot of tenant metadata for drift detection."""
    __tablename__ = "snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String)
    created_at = Column(DateTime, default=func.now())
    device_count = Column(Integer)
    control_count = Column(Integer)
    assignment_count = Column(Integer)
    notes = Column(Text)

    items = relationship("SnapshotItem", back_populates="snapshot", cascade="all, delete-orphan")


class SnapshotItem(Base):
    """Individual item within a snapshot."""
    __tablename__ = "snapshot_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id = Column(Integer, ForeignKey("snapshots.id", ondelete="CASCADE"), index=True)
    entity_type = Column(String)
    entity_id = Column(String, index=True)
    display_name = Column(String)
    raw_json = Column(Text)

    snapshot = relationship("Snapshot", back_populates="items")


# ---------------------------------------------------------------------------
# DeviceComplianceStatus
# ---------------------------------------------------------------------------
class DeviceComplianceStatus(Base):
    """Per-device per-policy compliance evaluation state."""
    __tablename__ = "device_compliance_statuses"

    id = Column(String, primary_key=True)
    device_id = Column(String, ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    policy_id = Column(String, index=True)
    policy_display_name = Column(String)
    status = Column(String)
    last_report_datetime = Column(DateTime)
    user_name = Column(String)
    user_principal_name = Column(String)
    raw_json = Column(Text)
    synced_at = Column(DateTime, default=func.now())

    device = relationship("Device", back_populates="compliance_statuses")


# ---------------------------------------------------------------------------
# Outcome (Explainability engine)
# ---------------------------------------------------------------------------
class Outcome(Base):
    """Observed or inferred state of a Control applied to a Device."""
    __tablename__ = "outcomes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    control_id = Column(String, ForeignKey("controls.id", ondelete="CASCADE"), index=True)
    device_id = Column(String, ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    status = Column(String)
    reason_code = Column(String)
    reason_detail = Column(Text)
    error_code = Column(String)
    source = Column(String)
    raw_json = Column(Text)
    synced_at = Column(DateTime, default=func.now())

    control = relationship("Control", back_populates="outcomes")

    __table_args__ = (
        Index("ix_outcome_device_control", "device_id", "control_id"),
    )


# ---------------------------------------------------------------------------
# DriftReport
# ---------------------------------------------------------------------------
class DriftReport(Base):
    """Report of changes detected between two snapshots."""
    __tablename__ = "drift_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=func.now())
    baseline_snapshot_id = Column(Integer, ForeignKey("snapshots.id"))
    current_snapshot_id = Column(Integer, ForeignKey("snapshots.id"))
    added_count = Column(Integer, default=0)
    removed_count = Column(Integer, default=0)
    modified_count = Column(Integer, default=0)
    report_json = Column(Text)

    def __repr__(self):
        return f"<DriftReport baseline={self.baseline_snapshot_id} current={self.current_snapshot_id}>"


# ---------------------------------------------------------------------------
# SyncLog
# ---------------------------------------------------------------------------
class SyncLog(Base):
    """Record of a sync run."""
    __tablename__ = "sync_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime, default=func.now())
    finished_at = Column(DateTime)
    status = Column(String)
    devices_synced = Column(Integer, default=0)
    controls_synced = Column(Integer, default=0)
    apps_synced = Column(Integer, default=0)
    error_message = Column(Text)
    details_json = Column(Text)
    details = Column(Text)
