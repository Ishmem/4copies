"""
HP LEDM (Low-End Data Model) Protocol Handler.
Parses and generates HP LEDM REST/XML payloads for device status, tray readiness, and ink supplies.
Matches specifications in hpygidDataMap.xml.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class InkSupplyState:
    color: str  # "Black" or "Tri-color"
    level_percent: int  # 0 to 100
    status: str  # "Ready", "Low", "Empty", "Missing"
    part_number: str  # e.g., "HP 63", "HP 664", "HP 803"
    serial_number: str = "N/A"


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

    def can_print(self) -> tuple[bool, str]:
        """Evaluates physical readiness to print based on LEDM telemetry."""
        if not self.is_ready:
            return False, "Device reported NOT READY"
        if self.input_tray_state == "PaperOut":
            return False, "Input tray is empty (Paper Out)"
        if self.input_tray_state == "PaperJam":
            return False, "Hardware error: Paper Jam detected"
        if self.black_ink.status == "Empty" and self.color_ink.status == "Empty":
            return False, "All ink cartridges are empty"
        if self.black_ink.status == "Missing":
            return False, "Black ink cartridge is missing"
        return True, "Printer ready"


class LEDMParser:
    """
    Parses and builds LEDM XML documents.
    """

    # XML namespaces used by HP LEDM
    NAMESPACES = {
        "dd": "http://www.hp.com/schemas/imaging/con/dictionaries/1.0/",
        "mhdyn": "http://www.hp.com/schemas/imaging/con/ledm/mediahandlingdyn/2007/11/20",
        "prdcfgdyn": "http://www.hp.com/schemas/imaging/con/ledm/productconfigdyn/2007/10/31",
        "prdcfgcap": "http://www.hp.com/schemas/imaging/con/ledm/productconfigcap/2007/10/31",
        "ss": "http://www.hp.com/schemas/imaging/con/ledm/shopforsupplies/2009/04/09",
    }

    @classmethod
    def parse_supplies_xml(cls, xml_text: str) -> Dict[str, InkSupplyState]:
        """Parses ShopForSupplies XML to extract ink cartridge levels."""
        root = ET.fromstring(xml_text)
        supplies = {}

        # Look for Consumable elements
        for consumable in root.iter():
            if consumable.tag.endswith("Consumable") or consumable.tag.endswith("Supply"):
                color = "Unknown"
                level = 100
                status = "Ready"
                part_no = "OEM"

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

                if color != "Unknown":
                    supplies[color] = InkSupplyState(
                        color=color,
                        level_percent=level,
                        status=status,
                        part_number=part_no
                    )

        return supplies

    @classmethod
    def build_mock_ledm_xml(cls, status: LEDMDeviceStatus) -> str:
        """Generates a valid LEDM XML representation of the device state."""
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
            ET.SubElement(c, "ConsumablePercentageLevelRemaining").text = str(ink.level_percent)
            ET.SubElement(c, "ConsumableState").text = ink.status
            ET.SubElement(c, "ConsumablePartNumber").text = ink.part_number

        return ET.tostring(root, encoding="utf-8").decode("utf-8")
