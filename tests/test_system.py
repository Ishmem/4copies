"""
Comprehensive Automated Test Suite for HP Device & Spooler Architecture.
"""

import tempfile
import unittest
from pathlib import Path

from hp_device_manager.config import DEFAULT_PRODUCT_GUID
from hp_device_manager.device_registry import DeviceInstance, DeviceRegistry
from hp_device_manager.ledm_protocol import LEDMDeviceStatus, LEDMParser
from hp_device_manager.pcl3_raster import PCL3RasterGenerator
from hp_device_manager.policy_store import PolicyStore
from hp_device_manager.spooler_manager import SpoolerManager
from hp_device_manager.telemetry_dispatcher import TelemetryDispatcher
from services.device_monitor_service import DeviceMonitorService


class TestHPSystemArchitecture(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_policy_store_persistence(self):
        store = PolicyStore(self.data_dir)
        self.assertFalse(store.settings.analytics_opt_in)
        self.assertTrue(store.settings.can_access_internet)
        self.assertFalse(store.is_telemetry_allowed())

        # Update and save
        store.settings.analytics_opt_in = True
        store.settings.fw_update_setting = "Auto"
        store.save()

        # Reload from disk
        store2 = PolicyStore(self.data_dir)
        self.assertTrue(store2.settings.analytics_opt_in)
        self.assertEqual(store2.settings.fw_update_setting, "Auto")
        self.assertTrue(store2.is_telemetry_allowed())

    def test_device_registry(self):
        registry = DeviceRegistry(self.data_dir)
        dev = DeviceInstance(
            device_guid=DEFAULT_PRODUCT_GUID,
            friendly_name="Test DeskJet 2130",
            port_name="USBPRINT002"
        )
        saved_file = registry.register_device(dev)
        self.assertTrue(saved_file.exists())

        loaded = registry.get_device(DEFAULT_PRODUCT_GUID)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.friendly_name, "Test DeskJet 2130")
        self.assertEqual(loaded.port_name, "USBPRINT002")

        devices = registry.list_devices()
        self.assertEqual(len(devices), 1)

    def test_ledm_status_and_readiness(self):
        status = LEDMDeviceStatus()
        can_print, _ = status.can_print()
        self.assertTrue(can_print)

        # Test paper out
        status.input_tray_state = "PaperOut"
        can_print, reason = status.can_print()
        self.assertFalse(can_print)
        self.assertIn("Paper Out", reason)

        # Test empty ink
        status.input_tray_state = "Ready"
        status.black_ink.status = "Empty"
        status.color_ink.status = "Empty"
        can_print, reason = status.can_print()
        self.assertFalse(can_print)
        self.assertIn("empty", reason)

    def test_pcl3_raster_generator(self):
        gen = PCL3RasterGenerator(resolution_dpi=300)
        gen.start_job("Unit Test Job")
        gen.begin_page()
        gen.send_raster_row(b"\xFF\xAA\x55\x00")
        gen.end_page()
        stream = gen.end_job()

        # Verify command markers
        self.assertTrue(stream.startswith(b"\x1b%-12345X"))
        self.assertIn(b"PCL3GUI", stream)
        self.assertIn(b"\x1b*v7S\x1b*r1A", stream)  # CmdBeginRaster
        self.assertIn(b"\x1b*b4W\xFF\xAA\x55\x00", stream)  # CmdSendBlockData
        self.assertIn(b"\x1b*rC", stream)  # CmdEndRaster
        self.assertIn(b"\x0c", stream)  # CmdFF

    def test_telemetry_privacy_gate(self):
        policy_store = PolicyStore(self.data_dir)
        dispatcher = TelemetryDispatcher(self.data_dir, policy_store)

        # With OptIn=False, event must be blocked
        res_blocked = dispatcher.dispatch_event("TEST", {"foo": "bar"})
        self.assertFalse(res_blocked["dispatched"])
        self.assertEqual(res_blocked["status"], "BLOCKED_BY_PRIVACY_POLICY")

        # Enable OptIn
        policy_store.settings.analytics_opt_in = True
        policy_store.save()

        res_ok = dispatcher.dispatch_event("TEST", {"foo": "bar"})
        self.assertTrue(res_ok["dispatched"])
        self.assertEqual(res_ok["status"], "STAGED_FOR_TRANSMISSION")
        self.assertTrue(Path(res_ok["queue_file"]).exists())

    def test_spooler_manager_enum(self):
        spooler = SpoolerManager()
        printers = spooler.enum_printers()
        self.assertIsInstance(printers, list)
        if printers:
            first = printers[0]["printer_name"]
            has_perm, _ = spooler.verify_print_permission(first)
            self.assertTrue(has_perm)

    def test_device_monitor_service_cycle(self):
        service = DeviceMonitorService(self.data_dir, poll_interval_sec=1.0, enable_logging=False)
        cycle_data = service.run_single_cycle()
        self.assertIn("overall_ready_to_print", cycle_data)
        self.assertIn("spooler", cycle_data)
        self.assertIn("ledm_hardware", cycle_data)
        self.assertTrue(service.state_file.exists())


if __name__ == "__main__":
    unittest.main()
