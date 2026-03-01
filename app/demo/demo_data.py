"""
app/demo/demo_data.py

Demo data loader — populates the local DB with synthetic data so the UI
can be explored without real Intune credentials.

Changes vs original:
  - DeviceAppStatus now covers ALL devices (was device_ids[:8])
  - Controls include realistic raw_json with platforms/technologies/templateReference
    so that _open_policy_portal() builds correct Intune portal URLs
  - DeviceComplianceStatus records created for all compliance policies × all devices
"""

import json
import logging
import random
from datetime import datetime, timedelta

from app.db.database import session_scope
from app.db.models import (
    Device, Control, Assignment, App, DeviceAppStatus,
    Group, SyncLog, DeviceComplianceStatus,
)

logger = logging.getLogger(__name__)

DEVICE_NAMES = [
    "DESKTOP-A1B2C3", "LAPTOP-HR-001", "SURFACE-CEO", "WIN11-DEV-42",
    "THINKPAD-T14", "DELL-XPS15", "HP-ELITEBOOK", "MACBOOK-INTUNE",
    "TABLET-SALES-3", "KIOSK-LOBBY-01", "WORKSTATION-FINANCE",
    "REMOTE-VPN-USER", "TESTDEVICE-QA", "AZURE-VM-PROD", "SHAREPOINT-KIOSK",
]

OS_LIST = ["Windows", "iOS", "Android", "macOS"]
COMPLIANCE_STATES = ["compliant", "noncompliant", "unknown", "error"]
OWNERSHIP_TYPES = ["company", "personal", "unknown"]

# (name, control_type, platform, technologies, template_family)
POLICY_DEFS = [
    ("Windows 10 Compliance - Corporate",  "compliance_policy",  "windows10", "mdm",              ""),
    ("BitLocker Enforcement Policy",        "settings_catalog",   "windows10", "mdm",              ""),
    ("Defender AV Configuration",           "settings_catalog",   "windows10", "mdm,microsoftSense",""),
    ("Windows Update Ring - Broad",         "config_policy",      "windows10", "mdm",              ""),
    ("Edge Browser Settings",               "settings_catalog",   "windows10", "mdm",              ""),
    ("VPN Client Configuration",            "config_policy",      "windows10", "mdm",              ""),
    ("Password Complexity - All Devices",   "compliance_policy",  "windows10", "mdm",              ""),
    ("iOS Compliance - Basic",              "compliance_policy",  "iOS",       "mdm",              ""),
    ("Android Work Profile Setup",          "settings_catalog",   "android",   "mdm",              ""),
    ("Firewall - Endpoint Security",        "endpoint_security",  "windows10", "endpointSecurity", ""),
    ("Conditional Access - MFA Required",   "compliance_policy",  "windows10", "mdm",              ""),
    ("LAPS Password Policy",               "settings_catalog",   "windows10", "mdm",              ""),
]

POLICY_NAMES = [p[0] for p in POLICY_DEFS]

APP_NAMES = [
    "Microsoft 365 Apps", "Microsoft Teams", "Slack", "Adobe Acrobat",
    "7-Zip", "Google Chrome", "Mozilla Firefox", "Zoom",
    "Visual Studio Code", "OneDrive",
]

GROUP_NAMES = [
    "SG-Intune-Windows-Corporate", "SG-Intune-iOS-BYOD",
    "SG-Finance-Devices", "SG-Remote-Workers", "SG-Executives",
    "SG-Kiosk-Devices", "SG-IT-Admins",
]


def load_demo_data() -> int:
    """Load demo data into the DB. Returns total object count."""
    logger.info("Loading demo data...")
    count = 0

    with session_scope() as db:
        # ── Groups ────────────────────────────────────────────────────────────
        group_ids = []
        for i, gname in enumerate(GROUP_NAMES):
            gid = f"demo-group-{i:04d}"
            g = Group(
                id=gid,
                display_name=gname,
                description=f"Demo group: {gname}",
                group_types='["Unified"]',
                is_dynamic=i % 3 == 0,
                member_count=random.randint(5, 120),
                synced_at=datetime.utcnow(),
                raw_json="{}",
            )
            db.merge(g)
            group_ids.append(gid)
            count += 1

        db.flush()

        # ── Controls (policies) ───────────────────────────────────────────────
        ctrl_ids = []
        compliance_ctrl_ids = []

        for i, (pname, ctrl_type, platform, technologies, tmpl_family) in enumerate(POLICY_DEFS):
            cid = f"demo-ctrl-{i:04d}"

            # Build realistic raw_json so portal URL builder works correctly
            raw = {
                "id": cid,
                "displayName": pname,
                "platforms": platform,
                "technologies": technologies,
                "templateReference": {
                    "templateId": "",
                    "templateFamily": tmpl_family,
                },
                "lastModifiedDateTime": (
                    datetime.utcnow() - timedelta(days=random.randint(1, 90))
                ).isoformat() + "Z",
            }

            c = Control(
                id=cid,
                display_name=pname,
                control_type=ctrl_type,
                platform=platform,
                description=f"Demo policy: {pname}",
                last_modified_datetime=datetime.utcnow() - timedelta(days=random.randint(1, 90)),
                is_assigned=True,
                assignment_count=random.randint(1, 4),
                api_source="demo",
                synced_at=datetime.utcnow(),
                raw_json=json.dumps(raw),
            )
            db.merge(c)
            ctrl_ids.append(cid)
            if ctrl_type == "compliance_policy":
                compliance_ctrl_ids.append((cid, pname))
            count += 1

        db.flush()

        # ── Assignments ───────────────────────────────────────────────────────
        for ctrl_id in ctrl_ids:
            num_assigns = random.randint(1, 3)
            for j in range(num_assigns):
                target = random.choice(["allDevices", "group"])
                gid = random.choice(group_ids) if target == "group" else None
                intent = "include" if random.random() > 0.2 else "exclude"
                aid = f"demo-assign-{ctrl_id[-4:]}-{j}"
                a = Assignment(
                    id=aid,
                    control_id=ctrl_id,
                    target_type=target,
                    target_id=gid if gid else "allDevices",
                    intent=intent,
                    synced_at=datetime.utcnow(),
                    raw_json="{}",
                )
                db.merge(a)
                count += 1

        db.flush()

        # ── Devices ───────────────────────────────────────────────────────────
        device_ids = []
        for i, dname in enumerate(DEVICE_NAMES):
            did = f"demo-device-{i:04d}"
            os_name = OS_LIST[i % len(OS_LIST)]
            d = Device(
                id=did,
                device_name=dname,
                serial_number=f"SN{random.randint(1000000, 9999999)}",
                device_type=os_name.lower(),
                operating_system=os_name,
                os_version=f"{random.randint(10, 14)}.{random.randint(0, 9)}.{random.randint(0, 9)}.{random.randint(0, 5000)}",
                compliance_state=random.choice(COMPLIANCE_STATES),
                management_state="managed",
                ownership=random.choice(OWNERSHIP_TYPES),
                enrolled_date_time=datetime.utcnow() - timedelta(days=random.randint(30, 730)),
                last_sync_date_time=datetime.utcnow() - timedelta(hours=random.randint(1, 72)),
                user_principal_name=f"user{i:03d}@contoso.com",
                user_display_name=f"Demo User {i}",
                model=random.choice(["Surface Pro 9", "ThinkPad T14", "Dell XPS 15", "HP EliteBook"]),
                manufacturer=random.choice(["Microsoft", "Lenovo", "Dell", "HP"]),
                encrypted=random.choice([True, False, None]),
                azure_ad_device_id=f"aad-{i:04d}-demo-0000-000000000000",
                synced_at=datetime.utcnow(),
                raw_json="{}",
            )
            db.merge(d)
            device_ids.append(did)
            count += 1

        db.flush()

        # ── Apps ──────────────────────────────────────────────────────────────
        app_ids = []
        for i, aname in enumerate(APP_NAMES):
            aid = f"demo-app-{i:04d}"
            a = App(
                id=aid,
                display_name=aname,
                app_type="winGetApp" if i % 3 != 0 else "iosStoreApp",
                publisher=random.choice([
                    "Microsoft", "Google", "Adobe", "Mozilla", "Slack Technologies"
                ]),
                is_assigned=True,
                last_modified_datetime=datetime.utcnow() - timedelta(days=random.randint(1, 60)),
                failed_device_count=random.randint(0, 5),
                synced_at=datetime.utcnow(),
                raw_json="{}",
            )
            db.merge(a)
            app_ids.append(aid)
            count += 1

        db.flush()

        # ── DeviceAppStatuses — ALL devices (was device_ids[:8]) ──────────────
        install_states = ["installed", "failed", "notInstalled", "pendingInstall", "unknown"]
        for did in device_ids:                          # ← all 15 devices
            for aid in random.sample(app_ids, k=min(4, len(app_ids))):
                das = DeviceAppStatus(
                    device_id=did,
                    app_id=aid,
                    install_state=random.choice(install_states),
                    error_code=random.choice([None, None, None, 0x87D1041C, 0x80070002]),
                    last_sync_date_time=datetime.utcnow() - timedelta(hours=random.randint(1, 48)),
                    device_name=next(
                        (dn for j, dn in enumerate(DEVICE_NAMES)
                         if f"demo-device-{j:04d}" == did), did
                    ),
                    synced_at=datetime.utcnow(),
                    raw_json="{}",
                )
                db.add(das)
                count += 1

        db.flush()

        # ── DeviceComplianceStatus — all compliance policies × all devices ────
        # Ensures "Show Assigned Devices" works for compliance policies in demo mode
        compliance_status_values = ["compliant", "noncompliant", "unknown", "error", "inGracePeriod"]
        for ctrl_id, ctrl_name in compliance_ctrl_ids:
            for j, did in enumerate(device_ids):
                record_id = f"{did}_{ctrl_id}_demo"
                dcs = DeviceComplianceStatus(
                    id=record_id,
                    device_id=did,
                    policy_id=ctrl_id,
                    policy_display_name=ctrl_name,
                    status=random.choice(compliance_status_values),
                    last_report_datetime=datetime.utcnow() - timedelta(hours=random.randint(1, 72)),
                    user_principal_name=f"user{j:03d}@contoso.com",
                    user_name=f"Demo User {j}",
                    raw_json="{}",
                    synced_at=datetime.utcnow(),
                )
                db.merge(dcs)
                count += 1

        db.flush()

        # ── SyncLog ───────────────────────────────────────────────────────────
        db.add(SyncLog(
            started_at=datetime.utcnow() - timedelta(minutes=2),
            finished_at=datetime.utcnow(),
            status="success",
            devices_synced=len(device_ids),
            controls_synced=len(ctrl_ids),
            apps_synced=len(app_ids),
            details_json='{"demo": true}',
        ))

    logger.info(f"Demo data loaded: {count} objects")
    return count
