"""
app/version.py

Single source of truth for the application version.

All modules that display or reference the version must import from here.
SemVer (MAJOR.MINOR.PATCH):
  1.0.0 — initial release
  1.1.0 — Remediations page, fixed portal deep-links (compliance/config/apps),
           centralised link builder, masked credentials, English README
"""

__version__ = "1.1.0"
APP_NAME = "Intune Dashboard"
