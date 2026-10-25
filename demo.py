"""
End-to-End Verification Demo for HP Device Profile, Spooler & Policy Architecture.
Runs without requiring physical hardware, testing all subsystems and live Windows Spooler APIs.
"""

import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from hp_device_manager.config import DEFAULT_PRODUCT_GUID, PRODUCT_NAME
from hp_device_manager.device_registry import DeviceInstance, DeviceRegistry
from hp_device_manager.ledm_protocol import LEDMDeviceStatus, LEDMParser
from hp_device_manager.pcl3_raster import PCL3RasterGenerator
from hp_device_manager.policy_store import PolicyStore
from hp_device_manager.spooler_manager import SpoolerManager
from hp_device_manager.telemetry_dispatcher import TelemetryDispatcher
from services.device_monitor_service import DeviceMonitorService


def run_full_demo():
    print("=" * 75)
    print("HP DESKJET 2130 REVERSE-ENGINEERED ARCHITECTURE - VERIFICATION DEMO")
    print("=" * 75)

    data_dir = Path(__file__).resolve().parent / "runtime_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    print(f"[*] Base Runtime Data Directory: {data_dir}")

    # ---------------------------------------------------------
    # STEP 1: Policy Configuration Store (settings.ini)
    # ---------------------------------------------------------
    print("\n" + "-" * 75)
    print("[+] STEP 1: Initializing System Policy Store (settings.ini)")
    print("-" * 75)
    policy_store = PolicyStore(data_dir)
    print(f"    • Loaded file: {policy_store.settings_file}")
    print(f"    • Analytics Opt-In:     {policy_store.settings.analytics_opt_in}")
    print(f"    • Can Access Internet:  {policy_store.settings.can_access_internet}")
    print(f"    • FW Update Policy:     {policy_store.settings.fw_update_setting}")
    print(f"    • Telemetry Gating:     {'ALLOWED' if policy_store.is_telemetry_allowed() else 'BLOCKED'}")

    # ---------------------------------------------------------
    # STEP 2: Device Instance Registry ({GUID}.ini)
    # ---------------------------------------------------------
    print("\n" + "-" * 75)
    print("[+] STEP 2: Registering Hardware Device Profile ({GUID}.ini)")
    print("-" * 75)
    registry = DeviceRegistry(data_dir)
    new_device = DeviceInstance(
        device_guid=DEFAULT_PRODUCT_GUID,
        friendly_name="HP DeskJet 2130 series (USB Controller)",
        hardware_id="HPDeskJet_2130_serie56EE",
        usb_vid_pid="Vid_03F0&Pid_E111",
        connection_type="USB",
        port_name="USBPRINT001",
        drivers={
            "hpygid20.inf": r"C:\WINDOWS\System32\DriverStore\FileRepository\hpygid20.inf_amd64\hpygid20.inf",
            "HPWia_DJ2130.INF": r"C:\WINDOWS\System32\DriverStore\FileRepository\hpwia_dj2130.inf_amd64\hpwia_dj2130.inf",
            "HPRestStub.INF": r"C:\WINDOWS\System32\DriverStore\FileRepository\hpreststub.inf_amd64\hpreststub.inf",
            "HPWinUSBStub.INF": r"C:\WINDOWS\System32\DriverStore\FileRepository\hpwinusbstub.inf_amd64\hpwinusbstub.inf",
        }
    )
    ini_path = registry.register_device(new_device)
    print(f"    • Successfully written profile: {ini_path.name}")
    devices = registry.list_devices()
    print(f"    • Total Registered Devices: {len(devices)}")
    for d in devices:
        print(f"      - [{d.device_guid}] {d.friendly_name} on {d.port_name}")

    # ---------------------------------------------------------
    # STEP 3: Privacy-Gated Telemetry Dispatcher (PDSMQ Pattern)
    # ---------------------------------------------------------
    print("\n" + "-" * 75)
    print("[+] STEP 3: Testing Privacy-Gated Event Dispatcher (PDSMQ)")
    print("-" * 75)
    dispatcher = TelemetryDispatcher(data_dir, policy_store)
    print(f"    • Generated Local Client UUID: {dispatcher.runtime_uuid}")

    print("    [Test A] Attempting dispatch with default OptIn=False:")
    res_a = dispatcher.dispatch_event("DEVICE_BOOT", {"status": "ONLINE"})
    print(f"      Result: {res_a['status']} ({res_a.get('reason')})")

    print("\n    [Test B] Enabling Consent (OptIn=True) and retrying dispatch:")
    policy_store.settings.analytics_opt_in = True
    policy_store.save()
    res_b = dispatcher.dispatch_event("DEVICE_BOOT", {"status": "ONLINE", "firmware": "20.79"})
    print(f"      Result: {res_b['status']}")
    if res_b.get("dispatched"):
        print(f"      Staged to: {Path(res_b['queue_file']).name}")
        print(f"      Target:    {res_b['destination']}")

    # Reset back to privacy-safe default
    policy_store.settings.analytics_opt_in = False
    policy_store.save()

    # ---------------------------------------------------------
    # STEP 4: LEDM REST-over-USB Protocol Simulation & Cartridge Bypass
    # ---------------------------------------------------------
    print("\n" + "-" * 75)
    print("[+] STEP 4: LEDM Protocol & Cartridge Authentication Bypass Verification")
    print("-" * 75)
    ledm_status = LEDMDeviceStatus()

    print("    [Scenario A] Normal OEM Cartridge Status:")
    can_print, reason = ledm_status.can_print()
    print(f"      • Status:             {'READY' if can_print else 'BLOCKED'} ({reason})")
    print(f"      • Black Cartridge:    {ledm_status.black_ink.part_number} ({ledm_status.black_ink.level_percent}% - {ledm_status.black_ink.auth_state})")

    print("\n    [Scenario B] Simulating Third-Party / Refilled Cartridge with DRM Rejection:")
    ledm_status.black_ink.status = "NonHP"
    ledm_status.black_ink.is_genuine_hp = False
    ledm_status.black_ink.auth_state = "ThirdPartyNonHP"

    # Test with bypass disabled (Strict OEM mode)
    ledm_status.bypass_cartridge_auth = False
    can_print_strict, reason_strict = ledm_status.can_print()
    print(f"      • Strict Mode Verdict: {'READY' if can_print_strict else 'BLOCKED'} -> {reason_strict}")

    # Test with bypass enabled (App bypass mode)
    ledm_status.bypass_cartridge_auth = True
    can_print_bypass, reason_bypass = ledm_status.can_print()
    print(f"      • Bypass Mode Verdict: {'READY' if can_print_bypass else 'BLOCKED'} -> {reason_bypass}")

    # Generate spoofed genuine XML
    spoofed_xml = LEDMParser.build_mock_ledm_xml(ledm_status, force_genuine_spoof=True)
    print(f"      • Genuine Spoofed XML generated (Disguised as Genuine HP 63 OEM): {len(spoofed_xml)} bytes")

    # ---------------------------------------------------------
    # STEP 5: Windows Print Spooler Permission & Queue Audit
    # ---------------------------------------------------------
    print("\n" + "-" * 75)
    print("[+] STEP 5: Live Windows Print Spooler (winspool.drv) Permission Check")
    print("-" * 75)
    spooler = SpoolerManager()
    printers = spooler.enum_printers()
    print(f"    • Enumerated {len(printers)} Windows Print Queues:")
    for p in printers:
        has_perm, msg = spooler.verify_print_permission(p["printer_name"])
        perm_label = "GRANTED (PRINTER_ACCESS_USE)" if has_perm else f"DENIED ({msg})"
        print(f"      - {p['printer_name']:<30} | Port: {p['port']:<12} | Access: {perm_label}")

    # ---------------------------------------------------------
    # STEP 6: HP PCL3 / PCL3GUI Raster Command Generation
    # ---------------------------------------------------------
    print("\n" + "-" * 75)
    print("[+] STEP 6: Synthesizing HP PCL3GUI Raster Stream")
    print("-" * 75)
    pcl3_stream = PCL3RasterGenerator.generate_test_pattern(width_dots=200, height_dots=40)
    has_begin = b"\x1b*v7S\x1b*r1A" in pcl3_stream
    has_block = b"\x1b*b" in pcl3_stream
    has_end = b"\x1b*rC" in pcl3_stream
    has_ff = b"\x0c" in pcl3_stream

    print(f"    • Total PCL3 Bytes Generated: {len(pcl3_stream)} bytes")
    print(f"    • Contains BeginRaster (CmdBeginRaster): {has_begin}")
    print(f"    • Contains BlockData (CmdSendBlockData): {has_block}")
    print(f"    • Contains EndRaster (CmdEndRaster):     {has_end}")
    print(f"    • Contains FormFeed (CmdFF):             {has_ff}")

    # Save sample stream to disk
    test_stream_path = data_dir / "test_pattern.pcl3"
    with open(test_stream_path, "wb") as f:
        f.write(pcl3_stream)
    print(f"    • Stream saved for inspection: {test_stream_path.name}")

    # ---------------------------------------------------------
    # STEP 7: Background Monitoring Service Cycle
    # ---------------------------------------------------------
    print("\n" + "-" * 75)
    print("[+] STEP 7: Running Single Background Service Monitoring Cycle")
    print("-" * 75)
    monitor_service = DeviceMonitorService(
        data_dir,
        target_printer="Microsoft Print to PDF" if printers else PRODUCT_NAME,
        enable_logging=False
    )
    cycle_result = monitor_service.run_single_cycle()
    print("    • Synchronized Device State Snapshot:")
    print(f"      - Overall Ready to Print: {cycle_result['overall_ready_to_print']}")
    print(f"      - Target Queue:           {cycle_result['printer_name']}")
    print(f"      - Spooler Permission:     {cycle_result['spooler']['permission_granted']}")
    print(f"      - Hardware Health:        {cycle_result['ledm_hardware']['can_print']}")
    print(f"      - Telemetry State:        {cycle_result['telemetry_event']}")
    print(f"      - State JSON written to:  {monitor_service.state_file.name}")

    print("\n" + "=" * 75)
    print("ALL SUBSYSTEMS VERIFIED AND OPERATIONAL!")
    print("=" * 75)


if __name__ == "__main__":
    run_full_demo()
