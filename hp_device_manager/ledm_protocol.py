"""
HP LEDM (Low-End Data Model) Protocol Handler.
Parses, generates, and spoofs HP LEDM REST/XML payloads for device status, tray readiness, and ink supplies.
Includes Cartridge Authentication Bypass and Genuine OEM Spoofing engine.
Matches specifications in hpygidDataMap.xml.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass
class InkSupplyState:
    color: str  # "Black" or "Tri-color"
    level_percent: int  # 0 to 100
    status: str  # "Ready", "Low", "Empty", "Missing", "NonHP", "Unauthorized", "Protected"
    part_number: str = "HP 63"  # OEM Part Number
    serial_number: str = "OEM-AUTHENTIC-2130"
    is_genuine_hp: bool = True
    auth_state: str = "GenuineOEM"  # "GenuineOEM", "Refilled", "ThirdPartyNonHP", "ProtectedBlock"

    def is_blocked(self) -> bool:
        """Checks if cartridge has an error or rejection state."""
        return self.status.lower() in (
            "empty",
            "missing",
            "nonhp",
            "unauthorized",
            "protected",
            "counterfeit",
            "error",
            "rejected",
        ) or not self.is_genuine_hp


@dataclass
class LEDMDeviceStatus:
    device_name: str = "HP DeskJet 2130 series"
    is_ready: bool = True
    duplex_unit: bool = False
    input_tray_state: str = "Ready"  # "Ready", "PaperOut", "PaperJam"
    num_input_trays: int = 1
    color_printing_supported: bool = True
    black_ink: InkSupplyState = field(
        default_factory=lambda: InkSupplyState("Black", 85, "Ready", "HP 63")
    )
    color_ink: InkSupplyState = field(
        default_factory=lambda: InkSupplyState("Tri-color", 90, "Ready", "HP 63")
    )

    # Cartridge Authentication Bypass & Spoof Controls
    bypass_cartridge_auth: bool = True
    spoof_genuine_status: bool = True
    ignore_low_ink: bool = True

    def can_print(self) -> Tuple[bool, str]:
        """
        Evaluates physical and logical readiness to print based on LEDM telemetry.
        When bypass_cartridge_auth is True, all cartridge DRM/rejections are suppressed.
        """
        if not self.is_ready:
            return False, "Device reported NOT READY"
        if self.input_tray_state == "PaperOut":
            return False, "Input tray is empty (Paper Out)"
        if self.input_tray_state == "PaperJam":
            return False, "Hardware error: Paper Jam detected"

        # Check cartridges
        has_cartridge_issue = self.black_ink.is_blocked() or self.color_ink.is_blocked()

        if has_cartridge_issue:
            if self.bypass_cartridge_auth:
                return True, "Cartridge authentication BYPASS active (Ignoring DRM/Auth locks)"
            else:
                # In strict mode, report the specific cartridge blockage
                if self.black_ink.status in ("NonHP", "Unauthorized", "Protected"):
                    return False, f"Cartridge blocked: Black cartridge rejected as {self.black_ink.status}"
                if self.color_ink.status in ("NonHP", "Unauthorized", "Protected"):
                    return False, f"Cartridge blocked: Tri-color cartridge rejected as {self.color_ink.status}"
                if self.black_ink.status == "Missing":
                    return False, "Black ink cartridge is missing"
                if self.black_ink.status == "Empty" and self.color_ink.status == "Empty":
                    return False, "All ink cartridges are empty"
                return False, "Cartridge authorization failed"

        return True, "Printer ready"


class LEDMParser:
    """
    Parses, builds, and spoofs LEDM XML documents.
    """

    NAMESPACES = {
        "dd": "http://www.hp.com/schemas/imaging/con/dictionaries/1.0/",
        "mhdyn": "http://www.hp.com/schemas/imaging/con/ledm/mediahandlingdyn/2007/11/20",
        "prdcfgdyn": "http://www.hp.com/schemas/imaging/con/ledm/productconfigdyn/2007/10/31",
        "prdcfgcap": "http://www.hp.com/schemas/imaging/con/ledm/productconfigcap/2007/10/31",
        "ss": "http://www.hp.com/schemas/imaging/con/ledm/shopforsupplies/2009/04/09",
    }

    @classmethod
    def parse_supplies_xml(cls, xml_text: str, apply_spoof: bool = False) -> Dict[str, InkSupplyState]:
        """
        Parses ShopForSupplies XML to extract ink cartridge levels.
        If apply_spoof is True, overrides any Non-HP, empty, or unauthenticated flags into Genuine OEM Ready.
        """
        root = ET.fromstring(xml_text)
        supplies = {}

        for consumable in root.iter():
            if consumable.tag.endswith("Consumable") or consumable.tag.endswith("Supply"):
                color = "Unknown"
                level = 100
                status = "Ready"
                part_no = "HP 63"
                brand = "HP"
                auth = "GenuineOEM"

                for child in consumable:
                    tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    text = child.text.strip() if child.text else ""

                    if tag in ("ConsumableColor", "Color"):
                        color = text
                    elif tag in ("ConsumablePercentageLevelRemaining", "Level"):
                        try:
                            level = int(text)
                        except ValueError:
                            level = 0
                    elif tag in ("ConsumableState", "Status"):
                        status = text
                    elif tag in ("ConsumablePartNumber", "PartNumber"):
                        part_no = text
                    elif tag in ("ConsumableBrand", "Brand"):
                        brand = text
                    elif tag in ("AuthenticityStatus", "AuthStatus"):
                        auth = text

                if apply_spoof:
                    # Spoof as genuine OEM ready
                    status = "Ready"
                    brand = "HP"
                    auth = "GenuineOEM"
                    part_no = "HP 63 (OEM Spoofed)"
                    if level <= 0:
                        level = 100

                if color != "Unknown":
                    supplies[color] = InkSupplyState(
                        color=color,
                        level_percent=level,
                        status=status,
                        part_number=part_no,
                        is_genuine_hp=(brand.upper() == "HP" and "NON" not in auth.upper()),
                        auth_state=auth,
                    )

        return supplies

    @classmethod
    def build_mock_ledm_xml(cls, status: LEDMDeviceStatus, force_genuine_spoof: bool = False) -> str:
        """
        Generates a valid LEDM XML representation of the device state.
        If force_genuine_spoof is True, all cartridges are disguised as Genuine HP OEM cartridges.
        """
        root = ET.Element("hpLedmProductStatus", xmlns=cls.NAMESPACES["dd"])

        # Media handling
        mh = ET.SubElement(root, "MediaHandlingDyn")
        tray = ET.SubElement(mh, "InputTray")
        ET.SubElement(tray, "InputBin").text = "Tray1"
        ET.SubElement(tray, "TrayState").text = status.input_tray_state
        ET.SubElement(mh, "NumOfInputTrays").text = str(status.num_input_trays)

        # Supplies
        supplies = ET.SubElement(root, "ShopForSupplies")
        for ink in (status.black_ink, status.color_ink):
            c = ET.SubElement(supplies, "Consumable")
            ET.SubElement(c, "ConsumableColor").text = ink.color

            if force_genuine_spoof or (status.spoof_genuine_status and status.bypass_cartridge_auth):
                # Spoofed OEM attributes
                ET.SubElement(c, "ConsumablePercentageLevelRemaining").text = str(max(ink.level_percent, 100))
                ET.SubElement(c, "ConsumableState").text = "Ready"
                ET.SubElement(c, "ConsumablePartNumber").text = "HP 63"
                ET.SubElement(c, "ConsumableBrand").text = "HP"
                ET.SubElement(c, "AuthenticityStatus").text = "GenuineOEM"
                ET.SubElement(c, "ProtectedCartridge").text = "False"
            else:
                # Real attributes
                ET.SubElement(c, "ConsumablePercentageLevelRemaining").text = str(ink.level_percent)
                ET.SubElement(c, "ConsumableState").text = ink.status
                ET.SubElement(c, "ConsumablePartNumber").text = ink.part_number
                ET.SubElement(c, "ConsumableBrand").text = "HP" if ink.is_genuine_hp else "Generic"
                ET.SubElement(c, "AuthenticityStatus").text = ink.auth_state
                ET.SubElement(c, "ProtectedCartridge").text = "True" if ink.status == "Protected" else "False"

        return ET.tostring(root, encoding="utf-8").decode("utf-8")
