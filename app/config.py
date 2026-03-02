"""
Application configuration - paths, defaults, and persistent settings.
app/config.py  —  v1.2.1
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "IntuneDashboard"
APP_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH         = APP_DIR / "intune_dashboard.db"
LOGS_DIR        = APP_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR      = APP_DIR / "exports"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
MSAL_CACHE_PATH = APP_DIR / "msal_cache.bin"
CONFIG_PATH     = APP_DIR / "config.json"

GRAPH_BASE_URL_V1   = "https://graph.microsoft.com/v1.0"
GRAPH_BASE_URL_BETA = "https://graph.microsoft.com/beta"

# Canonical scope list — one definition used everywhere.
# DeviceManagementConfiguration scopes removed in v1.2.1
# (Proactive Remediations feature removed).
DEFAULT_SCOPES = [
    "https://graph.microsoft.com/DeviceManagementManagedDevices.Read.All",
    "https://graph.microsoft.com/DeviceManagementApps.Read.All",
    "https://graph.microsoft.com/Group.Read.All",
    "https://graph.microsoft.com/User.Read.All",
    "https://graph.microsoft.com/Device.Read.All",
    "https://graph.microsoft.com/DeviceManagementRBAC.Read.All",
]

DEFAULT_CONFIG: Dict[str, Any] = {
    "tenant_id": "",
    "client_id": "",
    "auth_mode": "device_code",
    "cert_thumbprint": "",
    "cert_path": "",
    "db_path": str(DB_PATH),
    "export_dir": str(EXPORT_DIR),
    "sync_interval_minutes": 60,
    "sync_enabled": True,
    "demo_mode": False,
    "log_level": "INFO",
}


class AppConfig:
    _instance: Optional["AppConfig"] = None
    _data: Dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load()
        return cls._instance

    def _load(self):
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self._data = {**DEFAULT_CONFIG, **saved}
            except Exception as e:
                logger.warning(f"Failed to load config, using defaults: {e}")
                self._data = dict(DEFAULT_CONFIG)
        else:
            self._data = dict(DEFAULT_CONFIG)

    def save(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save config: {e}")

    def reload(self):
        self._load()

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value):
        self._data[key] = value

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._data.get(name, DEFAULT_CONFIG.get(name))
