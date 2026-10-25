"""
Privacy-Gated Telemetry Dispatcher (PDSMQ Pattern).
Enforces strict consent gates before staging or transmitting any diagnostic/telemetry events.
Matches reverse-engineered PDSMQ/PdsmqLocalSettings.xml & PdsmqConfig.xml behavior.
"""

from __future__ import annotations

import json
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Optional

from hp_device_manager.config import (
    PDS_DEFAULT_QUEUE,
    PDS_PROJECT_ID,
    PDS_SERVER_URI,
)
from hp_device_manager.policy_store import PolicyStore


class TelemetryDispatcher:
    """
    Manages local message queue state and privacy-gated event dispatch.
    """

    def __init__(
        self,
        data_dir: Path,
        policy_store: PolicyStore,
        project_id: str = PDS_PROJECT_ID,
        server_uri: str = PDS_SERVER_URI,
        queue_name: str = PDS_DEFAULT_QUEUE,
    ):
        self.data_dir = Path(data_dir)
        self.policy_store = policy_store
        self.project_id = project_id
        self.server_uri = server_uri
        self.queue_name = queue_name

        self.pdsmq_dir = self.data_dir / "PDSMQ"
        self.pdsmq_dir.mkdir(parents=True, exist_ok=True)
        self.local_settings_file = self.pdsmq_dir / "PdsmqLocalSettings.xml"
        self.runtime_uuid = self._init_runtime_uuid()

    def _init_runtime_uuid(self) -> str:
        """Loads existing AppDeployedUuid or creates a new random UUIDv4."""
        if self.local_settings_file.exists():
            try:
                tree = ET.parse(self.local_settings_file)
                root = tree.getroot()
                uuid_elem = root.find("AppDeployedUuid")
                if uuid_elem is not None and uuid_elem.text:
                    return uuid_elem.text.strip()
            except Exception:
                pass

        new_uuid = str(uuid.uuid4())
        self._write_local_settings(new_uuid)
        return new_uuid

    def _write_local_settings(self, runtime_uuid: str) -> None:
        """Writes PdsmqLocalSettings.xml matching HP's exact schema."""
        root = ET.Element("PdsmqConfig", version="3.1")
        setup = ET.SubElement(root, "Setup")
        ET.SubElement(setup, "UserOptIn").text = "True" if self.policy_store.settings.analytics_opt_in else "False"
        ET.SubElement(setup, "OnRamp").text = "/start_app/folder_exe"
        ET.SubElement(root, "AppDeployedUuid").text = runtime_uuid

        tree = ET.ElementTree(root)
        tree.write(self.local_settings_file, encoding="utf-8", xml_declaration=False)

    def dispatch_event(self, event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Attempts to stage or dispatch an event.
        Strict Privacy Gate: If Analytics OptIn is False or Internet Permissions are disabled,
        the event is completely dropped with NO network transmission.
        """
        # 1. Gate Check
        if not self.policy_store.settings.analytics_opt_in:
            return {
                "dispatched": False,
                "status": "BLOCKED_BY_PRIVACY_POLICY",
                "reason": "Analytics Opt-In is False in settings.ini",
            }

        if not self.policy_store.settings.can_access_internet:
            return {
                "dispatched": False,
                "status": "BLOCKED_BY_NETWORK_POLICY",
                "reason": "CanAccessInternet is False in settings.ini",
            }

        # 2. Build Envelope
        envelope = {
            "project_id": self.project_id,
            "runtime_uuid": self.runtime_uuid,
            "queue": self.queue_name,
            "timestamp": int(time.time()),
            "event_type": event_type,
            "data": payload,
        }

        # 3. Stage to local queue
        queue_file = self.pdsmq_dir / f"event_{int(time.time() * 1000)}.json"
        with open(queue_file, "w", encoding="utf-8") as f:
            json.dump(envelope, f, indent=2)

        return {
            "dispatched": True,
            "status": "STAGED_FOR_TRANSMISSION",
            "destination": f"{self.server_uri}/{self.queue_name}",
            "queue_file": str(queue_file),
            "envelope": envelope,
        }
