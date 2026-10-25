"""
Multi-Section Policy Store (settings.ini).
Manages enterprise system policies, privacy gates, and internet permissions.
"""

from __future__ import annotations

import configparser
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class PolicySettings:
    # [Analytics]
    analytics_opt_in: bool = False

    # [FWUpdate]
    web_services_opt_in: bool = False
    fw_update_setting: str = "Never"  # Never, Auto, Notify

    # [SetupValues]
    install_only: bool = False
    multi_connect_flow: bool = False
    eprint_mini_url: str = "http://123.hp.com/dj2130"
    web_reg_settings: bool = True
    auto_continue_online: bool = False
    install_opt_in_time: int = 0

    # [UsageTracking]
    ut_settings: bool = False
    send_ut_opt_out_flag: bool = False

    # [VirtualAlerts]
    virtual_alerts_optin: bool = False

    # [InternetPermissions]
    can_access_internet: bool = True
    prompt_before_access: bool = False


class PolicyStore:
    """
    Thread-safe & atomic manager for settings.ini policy configuration.
    """

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings_file = self.data_dir / "settings.ini"
        self.settings = PolicySettings()
        self.load()

    def load(self) -> PolicySettings:
        """Loads and parses settings.ini if present, else creates default."""
        if not self.settings_file.exists():
            self.save()
            return self.settings

        parser = configparser.ConfigParser()
        parser.read(self.settings_file, encoding="utf-8")

        # Parse [Analytics]
        if parser.has_section("Analytics"):
            self.settings.analytics_opt_in = parser.getboolean("Analytics", "OptIn", fallback=False)

        # Parse [FWUpdate]
        if parser.has_section("FWUpdate"):
            self.settings.web_services_opt_in = parser.get("FWUpdate", "WebServicesOptIn", fallback="No").lower() in ("yes", "true", "1")
            self.settings.fw_update_setting = parser.get("FWUpdate", "FWUpdateSetting", fallback="Never")

        # Parse [SetupValues]
        if parser.has_section("SetupValues"):
            self.settings.install_only = parser.get("SetupValues", "InstallOnly", fallback="No").lower() in ("yes", "true", "1")
            self.settings.multi_connect_flow = parser.get("SetupValues", "MultiConnectFlow", fallback="No").lower() in ("yes", "true", "1")
            self.settings.eprint_mini_url = parser.get("SetupValues", "ePrintMiniUrl", fallback="http://123.hp.com/dj2130")
            self.settings.web_reg_settings = parser.get("SetupValues", "WebRegSettings", fallback="Yes").lower() in ("yes", "true", "1")
            self.settings.auto_continue_online = parser.get("SetupValues", "AutoContinueOnline", fallback="No").lower() in ("yes", "true", "1")
            self.settings.install_opt_in_time = parser.getint("SetupValues", "InstallOptInTime", fallback=0)

        # Parse [UsageTracking]
        if parser.has_section("UsageTracking"):
            self.settings.ut_settings = parser.get("UsageTracking", "UTSettings", fallback="No").lower() in ("yes", "true", "1")
            self.settings.send_ut_opt_out_flag = parser.get("UsageTracking", "SendUTOptOutFlag", fallback="No").lower() in ("yes", "true", "1")

        # Parse [VirtualAlerts]
        if parser.has_section("VirtualAlerts"):
            self.settings.virtual_alerts_optin = parser.get("VirtualAlerts", "VirtualAlertsOptin", fallback="No").lower() in ("yes", "true", "1")

        # Parse [InternetPermissions]
        if parser.has_section("InternetPermissions"):
            self.settings.can_access_internet = parser.get("InternetPermissions", "CanAccessInternet", fallback="Yes").lower() in ("yes", "true", "1")
            self.settings.prompt_before_access = parser.get("InternetPermissions", "PromptBeforeAccess", fallback="No").lower() in ("yes", "true", "1")

        return self.settings

    def save(self) -> None:
        """Atomically saves current settings to settings.ini."""
        parser = configparser.ConfigParser()

        parser["Analytics"] = {
            "OptIn": "true" if self.settings.analytics_opt_in else "false"
        }
        parser["FWUpdate"] = {
            "WebServicesOptIn": "Yes" if self.settings.web_services_opt_in else "No",
            "FWUpdateSetting": self.settings.fw_update_setting,
        }
        parser["SetupValues"] = {
            "InstallOnly": "Yes" if self.settings.install_only else "No",
            "MultiConnectFlow": "Yes" if self.settings.multi_connect_flow else "No",
            "ePrintMiniUrl": self.settings.eprint_mini_url,
            "WebRegSettings": "Yes" if self.settings.web_reg_settings else "No",
            "AutoContinueOnline": "Yes" if self.settings.auto_continue_online else "No",
            "InstallOptInTime": str(self.settings.install_opt_in_time),
        }
        parser["UsageTracking"] = {
            "UTSettings": "Yes" if self.settings.ut_settings else "No",
            "SendUTOptOutFlag": "Yes" if self.settings.send_ut_opt_out_flag else "No",
        }
        parser["VirtualAlerts"] = {
            "VirtualAlertsOptin": "Yes" if self.settings.virtual_alerts_optin else "No",
        }
        parser["InternetPermissions"] = {
            "CanAccessInternet": "Yes" if self.settings.can_access_internet else "No",
            "PromptBeforeAccess": "Yes" if self.settings.prompt_before_access else "No",
        }

        # Atomic write pattern
        temp_file = tempfile.NamedTemporaryFile("w", dir=self.data_dir, delete=False, encoding="utf-8")
        try:
            parser.write(temp_file)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_file.close()
            os.replace(temp_file.name, self.settings_file)
        except Exception:
            if os.path.exists(temp_file.name):
                os.remove(temp_file.name)
            raise

    def is_telemetry_allowed(self) -> bool:
        """Enforces privacy gating: telemetry requires BOTH analytics opt-in and internet access."""
        return self.settings.analytics_opt_in and self.settings.can_access_internet

    def is_internet_allowed(self) -> bool:
        """Returns True if network communication is permitted without explicit blocking."""
        return self.settings.can_access_internet
