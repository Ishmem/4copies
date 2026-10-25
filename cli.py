"""
HP Device Profile, Spooler & Policy Management CLI.
Allows operators to inspect printer permissions, query queues, manage settings.ini, and test PCL3 printing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hp_device_manager.config import DEFAULT_PRODUCT_GUID, PRODUCT_NAME, get_default_system_dir
from hp_device_manager.device_registry import DeviceInstance, DeviceRegistry
from hp_device_manager.pcl3_raster import PCL3RasterGenerator
from hp_device_manager.policy_store import PolicyStore
from hp_device_manager.spooler_manager import SpoolerManager
from services.device_monitor_service import DeviceMonitorService


def get_data_dir(args) -> Path:
    if hasattr(args, "data_dir") and args.data_dir:
        return Path(args.data_dir)
    return Path(__file__).resolve().parent / "runtime_data"


def cmd_status(args):
    data_dir = get_data_dir(args)
    policy_store = PolicyStore(data_dir)
    spooler = SpoolerManager()

    print("=" * 70)
    print("HP SYSTEM STATUS & PRINT PERMISSION AUDIT")
    print("=" * 70)

    # 1. Spooler Printers
    print("\n[+] 1. Installed Windows Printers:")
    printers = spooler.enum_printers()
    if not printers:
        print("    (No printers enumerated)")
    for p in printers:
        perm_ok, perm_msg = spooler.verify_print_permission(p["printer_name"])
        perm_str = "GRANTED (PRINTER_ACCESS_USE)" if perm_ok else f"DENIED ({perm_msg})"
        print(f"    • Printer:  {p['printer_name']}")
        print(f"      Driver:   {p['driver']}")
        print(f"      Port:     {p['port']}")
        print(f"      Access:   {perm_str}")

    # 2. Policy State
    print("\n[+] 2. Active System Policies (settings.ini):")
    print(f"    • Analytics Opt-In:     {policy_store.settings.analytics_opt_in}")
    print(f"    • Can Access Internet:  {policy_store.settings.can_access_internet}")
    print(f"    • Firmware Update:      {policy_store.settings.fw_update_setting}")
    print(f"    • Telemetry Gating:     {'PERMITTED' if policy_store.is_telemetry_allowed() else 'BLOCKED'}")

    # 3. Device Profiles
    registry = DeviceRegistry(data_dir)
    devices = registry.list_devices()
    print(f"\n[+] 3. Registered Hardware Instances ({len(devices)}):")
    for d in devices:
        print(f"    • [{d.device_guid}] {d.friendly_name} (Port: {d.port_name})")
    print("=" * 70)


def cmd_policy_get(args):
    data_dir = get_data_dir(args)
    store = PolicyStore(data_dir)
    print(f"Configuration file: {store.settings_file}")
    print(f"Analytics OptIn:     {store.settings.analytics_opt_in}")
    print(f"Can Access Internet: {store.settings.can_access_internet}")
    print(f"Firmware Updates:    {store.settings.fw_update_setting}")
    print(f"Usage Tracking:      {store.settings.ut_settings}")


def cmd_policy_set(args):
    data_dir = get_data_dir(args)
    store = PolicyStore(data_dir)

    if args.optin is not None:
        store.settings.analytics_opt_in = args.optin.lower() in ("true", "1", "yes")
        print(f"Updated Analytics OptIn -> {store.settings.analytics_opt_in}")

    if args.internet is not None:
        store.settings.can_access_internet = args.internet.lower() in ("true", "1", "yes")
        print(f"Updated CanAccessInternet -> {store.settings.can_access_internet}")

    if args.update_setting is not None:
        store.settings.fw_update_setting = args.update_setting
        print(f"Updated FWUpdateSetting -> {store.settings.fw_update_setting}")

    store.save()
    print("Policies successfully updated and saved atomically.")


def cmd_device_register(args):
    data_dir = get_data_dir(args)
    registry = DeviceRegistry(data_dir)
    guid = args.guid or DEFAULT_PRODUCT_GUID
    name = args.name or PRODUCT_NAME

    dev = DeviceInstance(
        device_guid=guid,
        friendly_name=name,
        connection_type=args.connection or "USB",
        port_name=args.port or "USBPRINT001"
    )
    saved_path = registry.register_device(dev)
    print(f"[+] Successfully registered device profile to: {saved_path}")


def cmd_print_test(args):
    printer_name = args.printer
    print(f"Generating PCL3 raster test pattern for '{printer_name}'...")
    raw_pcl3 = PCL3RasterGenerator.generate_test_pattern(width_dots=300, height_dots=100)
    print(f"Generated {len(raw_pcl3)} bytes of PCL3 stream (ESC *v7S / ESC *r1A / ESC *b...W).")

    if args.output:
        out_file = Path(args.output)
        with open(out_file, "wb") as f:
            f.write(raw_pcl3)
        print(f"[+] Saved raw stream to file: {out_file}")
        return

    spooler = SpoolerManager()
    has_perm, msg = spooler.verify_print_permission(printer_name)
    if not has_perm:
        print(f"[-] Permission check failed: {msg}")
        return

    print(f"[+] Verified PRINTER_ACCESS_USE on '{printer_name}'. Submitting spool job...")
    ok, result_msg = spooler.submit_raw_print_job(printer_name, "PCL3 Diagnostics Test", raw_pcl3)
    if ok:
        print(f"[+] Success: {result_msg}")
    else:
        print(f"[-] Spool error: {result_msg}")


def cmd_service_run(args):
    data_dir = get_data_dir(args)
    printer_name = args.printer or PRODUCT_NAME
    service = DeviceMonitorService(data_dir, target_printer=printer_name, poll_interval_sec=args.interval)
    print(f"Starting DeviceMonitorService for '{printer_name}' in foreground. Press Ctrl+C to terminate.")
    try:
        service.start(run_in_background=False)
    except KeyboardInterrupt:
        service.stop()


def main():
    parser = argparse.ArgumentParser(description="HP Device Profile & Spooler Permission Management Suite")
    parser.add_argument("--data-dir", help="Path to data directory (defaults to ./runtime_data)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # status
    p_status = subparsers.add_parser("status", help="Display printer queue permissions and policies")
    p_status.set_defaults(func=cmd_status)

    # policy
    p_pol = subparsers.add_parser("policy", help="Manage settings.ini policies")
    pol_subs = p_pol.add_subparsers(dest="pol_command", required=True)
    p_pol_get = pol_subs.add_parser("get", help="Get current policies")
    p_pol_get.set_defaults(func=cmd_policy_get)
    p_pol_set = pol_subs.add_parser("set", help="Set policy flags")
    p_pol_set.add_argument("--optin", help="true or false")
    p_pol_set.add_argument("--internet", help="true or false")
    p_pol_set.add_argument("--update-setting", help="Never, Auto, Notify")
    p_pol_set.set_defaults(func=cmd_policy_set)

    # devices
    p_dev = subparsers.add_parser("devices", help="Manage {GUID}.ini device profiles")
    dev_subs = p_dev.add_subparsers(dest="dev_command", required=True)
    p_dev_list = dev_subs.add_parser("list", help="List registered device profiles")
    p_dev_list.set_defaults(func=lambda args: print([d.device_guid for d in DeviceRegistry(get_data_dir(args)).list_devices()]))
    p_dev_reg = dev_subs.add_parser("register", help="Register a new device instance")
    p_dev_reg.add_argument("--guid", help="Hardware GUID (default: {D82824A3-7576-4820-B68A-BB92F2ED1EDF})")
    p_dev_reg.add_argument("--name", help="Friendly name")
    p_dev_reg.add_argument("--port", help="Port name (default: USBPRINT001)")
    p_dev_reg.add_argument("--connection", help="USB or Network")
    p_dev_reg.set_defaults(func=cmd_device_register)

    # print-test
    p_print = subparsers.add_parser("print-test", help="Generate and send PCL3 test pattern")
    p_print.add_argument("--printer", default="Microsoft Print to PDF", help="Target printer name")
    p_print.add_argument("--output", help="Save raw PCL3 byte stream to file instead of spooling")
    p_print.set_defaults(func=cmd_print_test)

    # service
    p_srv = subparsers.add_parser("service", help="Run the background monitoring service")
    p_srv.add_argument("--printer", default=PRODUCT_NAME, help="Target printer name")
    p_srv.add_argument("--interval", type=float, default=2.0, help="Polling interval in seconds")
    p_srv.set_defaults(func=cmd_service_run)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
