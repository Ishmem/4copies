"""
Device Instance Registry ({GUID}.ini).
Maps hardware GUIDs to active DriverStore locations, interface endpoints, and port assignments.
"""

from __future__ import annotations

import configparser
import os
import re
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class DeviceInstance:
    device_guid: str
    friendly_name: str
    hardware_id: str = "HPDeskJet_2130_serie56EE"
    usb_vid_pid: str = "Vid_03F0&Pid_E111"
    connection_type: str = "USB"  # USB or Network
    port_name: str = "USBPRINT001"
    drivers: Dict[str, str] = field(default_factory=dict)
    update_drivers: Dict[str, str] = field(default_factory=dict)

    def is_valid_guid(self) -> bool:
        guid_clean = self.device_guid.strip("{}")
        try:
            uuid.UUID(guid_clean)
            return True
        except ValueError:
            return False


class DeviceRegistry:
    """
    Manages {GUID}.ini files in the system data directory.
    """

    GUID_FILE_PATTERN = re.compile(r"^\{[0-9a-fA-F\-]{36}\}\.ini$")

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def register_device(self, device: DeviceInstance) -> Path:
        """Serializes and saves a DeviceInstance to {GUID}.ini."""
        if not device.device_guid.startswith("{") or not device.device_guid.endswith("}"):
            device.device_guid = f"{{{device.device_guid.strip('{}')}}}"

        file_path = self.data_dir / f"{device.device_guid}.ini"
        parser = configparser.ConfigParser()

        parser["DeviceInfo"] = {
            "FriendlyName": device.friendly_name,
            "HardwareID": device.hardware_id,
            "USBID": device.usb_vid_pid,
            "ConnectionType": device.connection_type,
            "PortName": device.port_name,
        }

        parser["Drivers"] = device.drivers or {
            "hpygid20.inf": r"C:\WINDOWS\System32\DriverStore\FileRepository\hpygid20.inf_amd64\hpygid20.inf",
            "HPWia_DJ2130.INF": r"C:\WINDOWS\System32\DriverStore\FileRepository\hpwia_dj2130.inf_amd64\hpwia_dj2130.inf",
            "HPRestStub.INF": r"C:\WINDOWS\System32\DriverStore\FileRepository\hpreststub.inf_amd64\hpreststub.inf",
            "HPWinUSBStub.INF": r"C:\WINDOWS\System32\DriverStore\FileRepository\hpwinusbstub.inf_amd64\hpwinusbstub.inf",
        }

        if device.update_drivers:
            parser["UpdateDrivers"] = device.update_drivers

        # Write atomically
        temp_file = tempfile.NamedTemporaryFile("w", dir=self.data_dir, delete=False, encoding="utf-8")
        try:
            parser.write(temp_file)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_file.close()
            os.replace(temp_file.name, file_path)
        except Exception:
            if os.path.exists(temp_file.name):
                os.remove(temp_file.name)
            raise

        return file_path

    def get_device(self, guid: str) -> Optional[DeviceInstance]:
        """Loads a device profile by its GUID."""
        if not guid.startswith("{") or not guid.endswith("}"):
            guid = f"{{{guid.strip('{}')}}}"

        file_path = self.data_dir / f"{guid}.ini"
        if not file_path.exists():
            return None

        parser = configparser.ConfigParser()
        parser.read(file_path, encoding="utf-8")

        friendly_name = parser.get("DeviceInfo", "FriendlyName", fallback="Unknown Printer")
        hardware_id = parser.get("DeviceInfo", "HardwareID", fallback="HPDeskJet_2130_serie56EE")
        usb_vid_pid = parser.get("DeviceInfo", "USBID", fallback="Vid_03F0&Pid_E111")
        conn_type = parser.get("DeviceInfo", "ConnectionType", fallback="USB")
        port_name = parser.get("DeviceInfo", "PortName", fallback="USBPRINT001")

        drivers = {}
        if parser.has_section("Drivers"):
            drivers = dict(parser.items("Drivers"))

        update_drivers = {}
        if parser.has_section("UpdateDrivers"):
            update_drivers = dict(parser.items("UpdateDrivers"))

        return DeviceInstance(
            device_guid=guid,
            friendly_name=friendly_name,
            hardware_id=hardware_id,
            usb_vid_pid=usb_vid_pid,
            connection_type=conn_type,
            port_name=port_name,
            drivers=drivers,
            update_drivers=update_drivers,
        )

    def list_devices(self) -> List[DeviceInstance]:
        """Lists all registered device instances in the data directory."""
        devices = []
        for file in self.data_dir.glob("*.ini"):
            if self.GUID_FILE_PATTERN.match(file.name):
                guid = file.stem
                dev = self.get_device(guid)
                if dev:
                    devices.append(dev)
        return devices
