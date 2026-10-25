"""
Windows Print Spooler Manager.
Integrates directly with winspool.drv via ctypes for permission checks, status queries, and job spooling.
"""

from __future__ import annotations

import ctypes
import platform
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from hp_device_manager.config import (
    PRINTER_ACCESS_ADMINISTER,
    PRINTER_ACCESS_USE,
    PRINTER_ALL_ACCESS,
    PRINTER_STATUS_DOOR_OPEN,
    PRINTER_STATUS_ERROR,
    PRINTER_STATUS_NO_TONER,
    PRINTER_STATUS_OFFLINE,
    PRINTER_STATUS_OUT_OF_MEMORY,
    PRINTER_STATUS_PAPER_JAM,
    PRINTER_STATUS_PAPER_OUT,
    PRINTER_STATUS_PAPER_PROBLEM,
    PRINTER_STATUS_PAUSED,
    PRINTER_STATUS_PRINTING,
    PRINTER_STATUS_TONER_LOW,
    PRINTER_STATUS_USER_INTERVENTION,
)


# --- Win32 Spooler C Structures ---
class PRINTER_DEFAULTS(ctypes.Structure):
    _fields_ = [
        ("pDatatype", wintypes.LPWSTR),
        ("pDevMode", ctypes.c_void_p),
        ("DesiredAccess", wintypes.DWORD),
    ]


class DOC_INFO_1(ctypes.Structure):
    _fields_ = [
        ("pDocName", wintypes.LPWSTR),
        ("pOutputFile", wintypes.LPWSTR),
        ("pDatatype", wintypes.LPWSTR),
    ]


class PRINTER_INFO_2(ctypes.Structure):
    _fields_ = [
        ("pServerName", wintypes.LPWSTR),
        ("pPrinterName", wintypes.LPWSTR),
        ("pShareName", wintypes.LPWSTR),
        ("pPortName", wintypes.LPWSTR),
        ("pDriverName", wintypes.LPWSTR),
        ("pComment", wintypes.LPWSTR),
        ("pLocation", wintypes.LPWSTR),
        ("pDevMode", ctypes.c_void_p),
        ("pSepFile", wintypes.LPWSTR),
        ("pPrintProcessor", wintypes.LPWSTR),
        ("pDatatype", wintypes.LPWSTR),
        ("pParameters", wintypes.LPWSTR),
        ("pSecurityDescriptor", ctypes.c_void_p),
        ("Attributes", wintypes.DWORD),
        ("Priority", wintypes.DWORD),
        ("DefaultPriority", wintypes.DWORD),
        ("StartTime", wintypes.DWORD),
        ("UntilTime", wintypes.DWORD),
        ("Status", wintypes.DWORD),
        ("cJobs", wintypes.DWORD),
        ("AveragePPM", wintypes.DWORD),
    ]


@dataclass
class PrinterStatusReport:
    printer_name: str
    is_online: bool
    status_raw: int
    status_flags: List[str]
    job_count: int
    driver_name: str
    port_name: str
    can_print: bool
    permission_granted: bool
    detail: str


class SpoolerManager:
    """
    Direct interface to Windows Spooler API (winspool.drv).
    """

    def __init__(self):
        self.is_windows = platform.system() == "Windows"
        if self.is_windows:
            self.winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)
        else:
            self.winspool = None

    def enum_printers(self) -> List[Dict[str, str]]:
        """Enumerates local and connected network printers."""
        if not self.is_windows:
            return [{"printer_name": "Virtual HP DeskJet 2130", "port": "VIRTUAL_USB", "driver": "HP XPS Raster Common PCL3"}]

        flags = 0x00000002 | 0x00000004  # PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS
        needed = wintypes.DWORD()
        returned = wintypes.DWORD()

        self.winspool.EnumPrintersW(flags, None, 2, None, 0, ctypes.byref(needed), ctypes.byref(returned))
        if needed.value == 0:
            return []

        buf = (ctypes.c_byte * needed.value)()
        success = self.winspool.EnumPrintersW(flags, None, 2, buf, needed.value, ctypes.byref(needed), ctypes.byref(returned))
        if not success:
            return []

        array_type = PRINTER_INFO_2 * returned.value
        printers_struct = ctypes.cast(buf, ctypes.POINTER(array_type)).contents

        results = []
        for p in printers_struct:
            results.append({
                "printer_name": p.pPrinterName or "",
                "port": p.pPortName or "",
                "driver": p.pDriverName or "",
                "jobs": str(p.cJobs),
            })
        return results

    def verify_print_permission(self, printer_name: str, desired_access: int = PRINTER_ACCESS_USE) -> Tuple[bool, str]:
        """
        Validates whether current thread/process has permission to access the printer.
        """
        if not self.is_windows:
            return True, "POSIX Mock Environment - Access Allowed"

        defaults = PRINTER_DEFAULTS(None, None, desired_access)
        h_printer = wintypes.HANDLE()

        success = self.winspool.OpenPrinterW(printer_name, ctypes.byref(h_printer), ctypes.byref(defaults))
        if success:
            self.winspool.ClosePrinter(h_printer)
            return True, "Permission granted"
        else:
            err = ctypes.get_last_error()
            if err == 5:
                return False, "Access Denied (ERROR_ACCESS_DENIED: User lacks PRINTER_ACCESS_USE permission)"
            elif err == 1801:
                return False, "Invalid printer name (ERROR_INVALID_PRINTER_NAME)"
            return False, f"Win32 Error Code: {err}"

    def get_printer_status(self, printer_name: str, ignore_cartridge_lock: bool = True) -> PrinterStatusReport:
        """
        Queries queue status, job count, and active hardware error flags.
        When ignore_cartridge_lock is True, NO_TONER and USER_INTERVENTION cartridge locks are ignored.
        """
        if not self.is_windows:
            return PrinterStatusReport(
                printer_name=printer_name,
                is_online=True,
                status_raw=0,
                status_flags=["READY"],
                job_count=0,
                driver_name="HP PCL3 Mock Driver",
                port_name="USBPRINT001",
                can_print=True,
                permission_granted=True,
                detail="Mock POSIX Queue Ready"
            )

        defaults = PRINTER_DEFAULTS(None, None, PRINTER_ACCESS_USE)
        h_printer = wintypes.HANDLE()

        if not self.winspool.OpenPrinterW(printer_name, ctypes.byref(h_printer), ctypes.byref(defaults)):
            err = ctypes.get_last_error()
            return PrinterStatusReport(
                printer_name=printer_name,
                is_online=False,
                status_raw=0,
                status_flags=["ERROR_OPENING_HANDLE"],
                job_count=0,
                driver_name="Unknown",
                port_name="Unknown",
                can_print=False,
                permission_granted=False,
                detail=f"Cannot open printer: Win32 error {err}"
            )

        try:
            needed = wintypes.DWORD()
            self.winspool.GetPrinterW(h_printer, 2, None, 0, ctypes.byref(needed))
            if needed.value == 0:
                return PrinterStatusReport(
                    printer_name=printer_name,
                    is_online=False,
                    status_raw=0,
                    status_flags=["QUERY_FAILED"],
                    job_count=0,
                    driver_name="Unknown",
                    port_name="Unknown",
                    can_print=False,
                    permission_granted=True,
                    detail="GetPrinter buffer size 0"
                )

            buf = (ctypes.c_byte * needed.value)()
            if not self.winspool.GetPrinterW(h_printer, 2, buf, needed.value, ctypes.byref(needed)):
                return PrinterStatusReport(
                    printer_name=printer_name,
                    is_online=False,
                    status_raw=0,
                    status_flags=["GETPRINTER_FAILED"],
                    job_count=0,
                    driver_name="Unknown",
                    port_name="Unknown",
                    can_print=False,
                    permission_granted=True,
                    detail="Failed to read PRINTER_INFO_2"
                )

            p_info = ctypes.cast(buf, ctypes.POINTER(PRINTER_INFO_2)).contents
            status_val = p_info.Status
            flags = []

            if status_val & PRINTER_STATUS_PAUSED:
                flags.append("PAUSED")
            if status_val & PRINTER_STATUS_ERROR:
                flags.append("ERROR")
            if status_val & PRINTER_STATUS_PAPER_JAM:
                flags.append("PAPER_JAM")
            if status_val & PRINTER_STATUS_PAPER_OUT:
                flags.append("PAPER_OUT")
            if status_val & PRINTER_STATUS_OFFLINE:
                flags.append("OFFLINE")
            if status_val & PRINTER_STATUS_PRINTING:
                flags.append("PRINTING")
            if status_val & PRINTER_STATUS_TONER_LOW:
                flags.append("TONER_LOW")
            if status_val & PRINTER_STATUS_NO_TONER:
                flags.append("NO_TONER")
            if status_val & PRINTER_STATUS_USER_INTERVENTION:
                flags.append("USER_INTERVENTION_REQUIRED")
            if status_val & PRINTER_STATUS_DOOR_OPEN:
                flags.append("DOOR_OPEN")

            if not flags:
                flags.append("READY")

            if ignore_cartridge_lock:
                blocking_errors = ("PAPER_JAM", "PAPER_OUT", "OFFLINE", "ERROR")
            else:
                blocking_errors = ("PAPER_JAM", "PAPER_OUT", "NO_TONER", "USER_INTERVENTION_REQUIRED", "OFFLINE", "ERROR")

            can_print = not any(f in flags for f in blocking_errors)
            has_cartridge_lock = any(f in flags for f in ("NO_TONER", "TONER_LOW", "USER_INTERVENTION_REQUIRED"))

            if can_print:
                if has_cartridge_lock and ignore_cartridge_lock:
                    detail = f"Queue ready (Cartridge Lock Bypassed: {', '.join(f for f in flags if f in ('NO_TONER', 'TONER_LOW', 'USER_INTERVENTION_REQUIRED'))})"
                else:
                    detail = "Queue is ready for submission"
            else:
                detail = f"Queue blocked by: {', '.join(flags)}"

            return PrinterStatusReport(
                printer_name=p_info.pPrinterName or printer_name,
                is_online="OFFLINE" not in flags,
                status_raw=status_val,
                status_flags=flags,
                job_count=p_info.cJobs,
                driver_name=p_info.pDriverName or "",
                port_name=p_info.pPortName or "",
                can_print=can_print,
                permission_granted=True,
                detail=detail
            )
        finally:
            self.winspool.ClosePrinter(h_printer)

    def submit_raw_print_job(self, printer_name: str, doc_name: str, raw_bytes: bytes) -> Tuple[bool, str]:
        """
        Submits a raw byte stream (PCL3/PostScript/RAW) to the Windows Print Spooler.
        """
        if not self.is_windows:
            return True, f"POSIX Mock: Dispatched {len(raw_bytes)} bytes to virtual spooler."

        defaults = PRINTER_DEFAULTS(None, None, PRINTER_ACCESS_USE)
        h_printer = wintypes.HANDLE()

        if not self.winspool.OpenPrinterW(printer_name, ctypes.byref(h_printer), ctypes.byref(defaults)):
            return False, f"OpenPrinter failed: Win32 error {ctypes.get_last_error()}"

        try:
            doc_info = DOC_INFO_1(doc_name, None, "RAW")
            job_id = self.winspool.StartDocPrinterW(h_printer, 1, ctypes.byref(doc_info))
            if job_id == 0:
                return False, f"StartDocPrinter failed: Win32 error {ctypes.get_last_error()}"

            try:
                if not self.winspool.StartPagePrinter(h_printer):
                    return False, f"StartPagePrinter failed: Win32 error {ctypes.get_last_error()}"

                written = wintypes.DWORD()
                success = self.winspool.WritePrinter(
                    h_printer,
                    raw_bytes,
                    len(raw_bytes),
                    ctypes.byref(written)
                )
                self.winspool.EndPagePrinter(h_printer)

                if not success or written.value != len(raw_bytes):
                    return False, f"WritePrinter failed: wrote {written.value}/{len(raw_bytes)} bytes."

                return True, f"Successfully spooled job #{job_id} ({written.value} bytes) to {printer_name}"
            finally:
                self.winspool.EndDocPrinter(h_printer)
        finally:
            self.winspool.ClosePrinter(h_printer)
