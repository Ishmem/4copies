"""
HP Background Device & Spooler Monitoring Service.
Simulates and implements the background monitoring service (like hpqDTSS.exe / HPNetworkCommunicatorCom.exe).
Periodically checks spooler queues, queries LEDM device telemetry, updates local state, and respects privacy policies.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from hp_device_manager.device_registry import DeviceRegistry
from hp_device_manager.ledm_protocol import LEDMDeviceStatus, LEDMParser
from hp_device_manager.policy_store import PolicyStore
from hp_device_manager.spooler_manager import SpoolerManager
from hp_device_manager.telemetry_dispatcher import TelemetryDispatcher


class DeviceMonitorService:
    """
    Continuous background daemon for printer status polling, policy adherence, and health reporting.
    """

    def __init__(
        self,
        data_dir: Path,
        target_printer: str = "HP DeskJet 2130 series",
        poll_interval_sec: float = 3.0,
        enable_logging: bool = True,
    ):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.target_printer = target_printer
        self.poll_interval = poll_interval_sec
        self.running = False
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

        # Core subsystems
        self.policy_store = PolicyStore(self.data_dir)
        self.registry = DeviceRegistry(self.data_dir)
        self.spooler = SpoolerManager()
        self.dispatcher = TelemetryDispatcher(self.data_dir, self.policy_store)
        self.device_status = LEDMDeviceStatus(device_name=target_printer)

        # Status output file for IPC with GUI utilities (e.g. Toolbox)
        self.state_file = self.data_dir / "device_state.json"

        # Setup logger
        self.logger = logging.getLogger("DeviceMonitorService")
        if enable_logging and not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter("[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s"))
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

    def start(self, run_in_background: bool = False) -> None:
        """Starts the monitoring loop."""
        self.running = True
        self._stop_event.clear()
        self.logger.info(f"Starting Device Monitor Service for '{self.target_printer}' (Poll Interval: {self.poll_interval}s)")

        if run_in_background:
            self._worker_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self._worker_thread.start()
        else:
            self._monitor_loop()

    def stop(self) -> None:
        """Signals the monitoring loop to terminate gracefully."""
        self.logger.info("Stopping Device Monitor Service...")
        self.running = False
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5.0)
        self.logger.info("Device Monitor Service stopped.")

    def run_single_cycle(self) -> dict:
        """Executes a single check and state synchronization cycle."""
        # 1. Reload policies in case settings.ini changed
        self.policy_store.load()
        bypass_auth = self.policy_store.settings.bypass_cartridge_auth
        self.device_status.bypass_cartridge_auth = bypass_auth
        self.device_status.spoof_genuine_status = self.policy_store.settings.spoof_genuine_status
        self.device_status.ignore_low_ink = self.policy_store.settings.ignore_low_ink

        # 2. Check Windows Spooler Queue
        spooler_report = self.spooler.get_printer_status(self.target_printer, ignore_cartridge_lock=bypass_auth)
        has_permission, perm_detail = self.spooler.verify_print_permission(self.target_printer)

        # 3. Check Physical Device Health (LEDM)
        ledm_can_print, ledm_reason = self.device_status.can_print()

        # 4. Synthesize overall state
        overall_ready = spooler_report.can_print and has_permission and ledm_can_print
        state_data = {
            "timestamp": int(time.time()),
            "printer_name": self.target_printer,
            "overall_ready_to_print": overall_ready,
            "cartridge_auth": {
                "bypass_enabled": bypass_auth,
                "spoof_genuine": self.policy_store.settings.spoof_genuine_status,
                "status": "AUTHENTICATION_BYPASSED" if bypass_auth else "STRICT_OEM_ENFORCEMENT",
            },
            "spooler": {
                "online": spooler_report.is_online,
                "status_flags": spooler_report.status_flags,
                "pending_jobs": spooler_report.job_count,
                "driver": spooler_report.driver_name,
                "port": spooler_report.port_name,
                "permission_granted": has_permission,
                "permission_detail": perm_detail,
            },
            "ledm_hardware": {
                "can_print": ledm_can_print,
                "reason": ledm_reason,
                "tray_state": self.device_status.input_tray_state,
                "black_ink_percent": self.device_status.black_ink.level_percent,
                "color_ink_percent": self.device_status.color_ink.level_percent,
                "black_ink_status": self.device_status.black_ink.status,
                "color_ink_status": self.device_status.color_ink.status,
            },
            "policies": {
                "analytics_opt_in": self.policy_store.settings.analytics_opt_in,
                "can_access_internet": self.policy_store.settings.can_access_internet,
                "update_setting": self.policy_store.settings.fw_update_setting,
            },
        }

        # 5. Persist state for IPC
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(state_data, f, indent=2)

        # 6. Dispatch heartbeat if permitted by policies
        telemetry_result = self.dispatcher.dispatch_event("HEARTBEAT", {
            "printer": self.target_printer,
            "jobs": spooler_report.job_count,
            "black_ink": self.device_status.black_ink.level_percent,
        })
        state_data["telemetry_event"] = telemetry_result["status"]

        return state_data

    def _monitor_loop(self) -> None:
        """Internal execution loop."""
        while not self._stop_event.is_set():
            try:
                cycle_data = self.run_single_cycle()
                spooler = cycle_data["spooler"]
                ledm = cycle_data["ledm_hardware"]
                self.logger.info(
                    f"Heartbeat | Spooler: {spooler['status_flags']} (Jobs: {spooler['pending_jobs']}) | "
                    f"Ink: K={ledm['black_ink_percent']}%, C={ledm['color_ink_percent']}% | "
                    f"Print Permission: {spooler['permission_granted']} | "
                    f"Telemetry: {cycle_data['telemetry_event']}"
                )
            except Exception as e:
                self.logger.error(f"Error during monitor cycle: {e}", exc_info=True)

            self._stop_event.wait(self.poll_interval)


if __name__ == "__main__":
    data_directory = Path(__file__).resolve().parent.parent / "runtime_data"
    service = DeviceMonitorService(data_directory, poll_interval_sec=2.0)

    # Handle Ctrl+C
    def handle_sig(sig, frame):
        service.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    print("Starting service in foreground. Press Ctrl+C to stop.")
    service.start(run_in_background=False)
