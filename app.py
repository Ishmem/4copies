"""
HP DeskJet 2130 Device Assistant & Spooler Manager.
A simple, modern desktop GUI app for managing printer permissions, ink levels, policies, and PCL3 print jobs.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

# Project imports
from hp_device_manager.config import DEFAULT_PRODUCT_GUID, PRODUCT_NAME
from hp_device_manager.device_registry import DeviceInstance, DeviceRegistry
from hp_device_manager.ledm_protocol import LEDMDeviceStatus
from hp_device_manager.pcl3_raster import PCL3RasterGenerator
from hp_device_manager.policy_store import PolicyStore
from hp_device_manager.spooler_manager import SpoolerManager
from services.device_monitor_service import DeviceMonitorService


class PrinterAssistantApp(tk.Tk):
    """
    Modern Desktop GUI App for HP Device Profile & Spooler Management.
    """

    COLOR_PRIMARY = "#0096D6"     # HP Blue
    COLOR_PRIMARY_DARK = "#0073A8"
    COLOR_BG = "#F1F5F9"          # Light Slate BG
    COLOR_CARD = "#FFFFFF"        # White Card
    COLOR_TEXT = "#0F172A"        # Slate 900
    COLOR_MUTED = "#64748B"       # Slate 500
    COLOR_SUCCESS = "#10B981"     # Emerald Green
    COLOR_WARNING = "#F59E0B"     # Amber
    COLOR_DANGER = "#EF4444"      # Rose Red
    COLOR_BORDER = "#E2E8F0"

    def __init__(self):
        super().__init__()
        self.title("HP DeskJet 2130 - Device Assistant & Print Manager")
        self.geometry("960x680")
        self.minsize(850, 600)
        self.configure(bg=self.COLOR_BG)

        # Paths and managers
        self.data_dir = Path(__file__).resolve().parent / "runtime_data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.policy_store = PolicyStore(self.data_dir)
        self.registry = DeviceRegistry(self.data_dir)
        self.spooler = SpoolerManager()
        self.ledm_status = LEDMDeviceStatus(
            device_name=PRODUCT_NAME,
            bypass_cartridge_auth=self.policy_store.settings.bypass_cartridge_auth,
            spoof_genuine_status=self.policy_store.settings.spoof_genuine_status,
            ignore_low_ink=self.policy_store.settings.ignore_low_ink,
        )

        # Ensure default device is registered in {GUID}.ini
        if not self.registry.get_device(DEFAULT_PRODUCT_GUID):
            self.registry.register_device(DeviceInstance(
                device_guid=DEFAULT_PRODUCT_GUID,
                friendly_name=PRODUCT_NAME,
                port_name="USBPRINT001"
            ))

        # Background service state
        self.monitor_service: DeviceMonitorService | None = None
        self.service_running = False

        self._setup_styles()
        self._build_ui()
        self._refresh_all_data()

    def _setup_styles(self):
        self.style = ttk.Style(self)
        self.style.theme_use("clam")

        self.style.configure(".", font=("Segoe UI", 9), background=self.COLOR_BG)
        self.style.configure("Card.TFrame", background=self.COLOR_CARD, relief="flat")
        
        # Primary Action Button
        self.style.configure(
            "Primary.TButton",
            font=("Segoe UI", 9, "bold"),
            background=self.COLOR_PRIMARY,
            foreground="#FFFFFF",
            padding=6,
            borderwidth=0
        )
        self.style.map("Primary.TButton", background=[("active", self.COLOR_PRIMARY_DARK)])

        # Secondary Button
        self.style.configure(
            "Secondary.TButton",
            font=("Segoe UI", 9),
            background="#E2E8F0",
            foreground=self.COLOR_TEXT,
            padding=5,
            borderwidth=0
        )
        self.style.map("Secondary.TButton", background=[("active", "#CBD5E1")])

        # Ink Progress Bars
        self.style.configure("BlackInk.Horizontal.TProgressbar", troughcolor="#E2E8F0", background="#1E293B")
        self.style.configure("ColorInk.Horizontal.TProgressbar", troughcolor="#E2E8F0", background="#0284C7")

    def _build_ui(self):
        # 1. Header Banner
        header = tk.Frame(self, bg=self.COLOR_PRIMARY, height=70)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        title_box = tk.Frame(header, bg=self.COLOR_PRIMARY)
        title_box.pack(side="left", padx=20, pady=12)

        tk.Label(
            title_box,
            text="HP DeskJet 2130 series",
            font=("Segoe UI", 16, "bold"),
            fg="#FFFFFF",
            bg=self.COLOR_PRIMARY
        ).pack(anchor="w")

        tk.Label(
            title_box,
            text="USB Controller: VID_03F0 & PID_E111 • Windows Spooler Architecture",
            font=("Segoe UI", 8),
            fg="#E0F2FE",
            bg=self.COLOR_PRIMARY
        ).pack(anchor="w")

        # Global Status Badge
        self.status_badge = tk.Label(
            header,
            text="● READY TO PRINT",
            font=("Segoe UI", 9, "bold"),
            fg="#FFFFFF",
            bg=self.COLOR_SUCCESS,
            padx=12,
            pady=4
        )
        self.status_badge.pack(side="right", padx=20, pady=18)

        # 2. Main Content Area (3 Cards in Grid)
        main_content = tk.Frame(self, bg=self.COLOR_BG)
        main_content.pack(fill="both", expand=True, padx=20, pady=15)
        main_content.columnconfigure(0, weight=1)
        main_content.columnconfigure(1, weight=1)
        main_content.columnconfigure(2, weight=1)
        main_content.rowconfigure(0, weight=1)

        # CARD 1: Windows Spooler & Permissions
        self._build_spooler_card(main_content)

        # CARD 2: Supplies & LEDM Telemetry
        self._build_supplies_card(main_content)

        # CARD 3: Policies & Privacy Gate
        self._build_policy_card(main_content)

        # 3. Bottom Card: Background Monitor & Log Console
        self._build_bottom_card()

    def _build_spooler_card(self, parent):
        card = ttk.Frame(parent, style="Card.TFrame", padding=15)
        card.grid(row=0, column=0, sticky="nsew", padx=6)

        # Card Title
        tk.Label(card, text="🖨️ Windows Print Queue", font=("Segoe UI", 12, "bold"), fg=self.COLOR_TEXT, bg=self.COLOR_CARD).pack(anchor="w", pady=(0, 10))

        # Printer Selector
        tk.Label(card, text="Select Active Printer:", font=("Segoe UI", 9), fg=self.COLOR_MUTED, bg=self.COLOR_CARD).pack(anchor="w")
        self.printer_combo = ttk.Combobox(card, state="readonly", font=("Segoe UI", 9))
        self.printer_combo.pack(fill="x", pady=(2, 10))
        self.printer_combo.bind("<<ComboboxSelected>>", self._on_printer_selected)

        # Permission Indicator
        perm_frame = tk.Frame(card, bg="#F8FAFC", bd=1, relief="solid")
        perm_frame.pack(fill="x", pady=6, ipady=6, ipadx=8)

        tk.Label(perm_frame, text="Spooler Permission:", font=("Segoe UI", 8, "bold"), fg=self.COLOR_MUTED, bg="#F8FAFC").pack(anchor="w")
        self.lbl_perm_status = tk.Label(perm_frame, text="Checking...", font=("Segoe UI", 10, "bold"), fg=self.COLOR_SUCCESS, bg="#F8FAFC")
        self.lbl_perm_status.pack(anchor="w")

        # Queue Details
        self.lbl_queue_details = tk.Label(card, text="Port: -\nDriver: -\nPending Jobs: 0", justify="left", font=("Segoe UI", 8), fg=self.COLOR_MUTED, bg=self.COLOR_CARD)
        self.lbl_queue_details.pack(anchor="w", pady=8)

        # Action Buttons
        ttk.Button(card, text="🖨️ Print PCL3 Test Pattern", style="Primary.TButton", command=self._send_test_print).pack(fill="x", pady=(10, 4))
        ttk.Button(card, text="🔄 Refresh Queues", style="Secondary.TButton", command=self._refresh_spooler).pack(fill="x")

    def _build_supplies_card(self, parent):
        card = ttk.Frame(parent, style="Card.TFrame", padding=15)
        card.grid(row=0, column=1, sticky="nsew", padx=6)

        tk.Label(card, text="💧 Supplies & Cartridge Auth", font=("Segoe UI", 12, "bold"), fg=self.COLOR_TEXT, bg=self.COLOR_CARD).pack(anchor="w", pady=(0, 6))

        # Auth Bypass Banner
        self.lbl_auth_pill = tk.Label(
            card,
            text="🛡️ CARTRIDGE AUTH BYPASS: ACTIVE",
            font=("Segoe UI", 8, "bold"),
            fg="#FFFFFF",
            bg="#8B5CF6",
            padx=8,
            pady=3
        )
        self.lbl_auth_pill.pack(fill="x", pady=(0, 10))

        # Black Ink
        tk.Label(card, text="Black Cartridge (HP 63)", font=("Segoe UI", 9, "bold"), fg=self.COLOR_TEXT, bg=self.COLOR_CARD).pack(anchor="w")
        self.lbl_black_pct = tk.Label(card, text="85% - Ready (Genuine OEM)", font=("Segoe UI", 8), fg=self.COLOR_MUTED, bg=self.COLOR_CARD)
        self.lbl_black_pct.pack(anchor="w")
        self.prog_black = ttk.Progressbar(card, style="BlackInk.Horizontal.TProgressbar", length=200, value=85)
        self.prog_black.pack(fill="x", pady=(2, 10))

        # Tri-Color Ink
        tk.Label(card, text="Tri-Color Cartridge (HP 63)", font=("Segoe UI", 9, "bold"), fg=self.COLOR_TEXT, bg=self.COLOR_CARD).pack(anchor="w")
        self.lbl_color_pct = tk.Label(card, text="90% - Ready (Genuine OEM)", font=("Segoe UI", 8), fg=self.COLOR_MUTED, bg=self.COLOR_CARD)
        self.lbl_color_pct.pack(anchor="w")
        self.prog_color = ttk.Progressbar(card, style="ColorInk.Horizontal.TProgressbar", length=200, value=90)
        self.prog_color.pack(fill="x", pady=(2, 10))

        # Paper Tray State
        tk.Label(card, text="Input Tray 1:", font=("Segoe UI", 9, "bold"), fg=self.COLOR_TEXT, bg=self.COLOR_CARD).pack(anchor="w")
        self.lbl_tray_status = tk.Label(card, text="Ready (Plain Paper loaded)", font=("Segoe UI", 8), fg=self.COLOR_SUCCESS, bg=self.COLOR_CARD)
        self.lbl_tray_status.pack(anchor="w", pady=(0, 8))

        # Interactive Simulation Controls
        sim_box = tk.LabelFrame(card, text="Simulate Cartridge / Hardware States", font=("Segoe UI", 8), bg=self.COLOR_CARD, fg=self.COLOR_MUTED, padx=6, pady=6)
        sim_box.pack(fill="x", pady=(2, 0))

        row1 = tk.Frame(sim_box, bg=self.COLOR_CARD)
        row1.pack(fill="x", pady=1)
        ttk.Button(row1, text="Non-HP / Refilled", style="Secondary.TButton", command=self._sim_non_hp).pack(side="left", expand=True, fill="x", padx=1)
        ttk.Button(row1, text="Depleted (0%)", style="Secondary.TButton", command=self._sim_low_ink).pack(side="left", expand=True, fill="x", padx=1)

        row2 = tk.Frame(sim_box, bg=self.COLOR_CARD)
        row2.pack(fill="x", pady=1)
        ttk.Button(row2, text="Paper Out", style="Secondary.TButton", command=self._sim_paper_out).pack(side="left", expand=True, fill="x", padx=1)
        ttk.Button(row2, text="Reset to OEM", style="Secondary.TButton", command=self._sim_reset_ok).pack(side="left", expand=True, fill="x", padx=1)

    def _build_policy_card(self, parent):
        card = ttk.Frame(parent, style="Card.TFrame", padding=15)
        card.grid(row=0, column=2, sticky="nsew", padx=6)

        tk.Label(card, text="🛡️ Policies & Cartridge Bypasses", font=("Segoe UI", 12, "bold"), fg=self.COLOR_TEXT, bg=self.COLOR_CARD).pack(anchor="w", pady=(0, 6))

        # Checkboxes for Cartridge Bypass
        self.var_bypass_auth = tk.BooleanVar(value=self.policy_store.settings.bypass_cartridge_auth)
        self.var_spoof_genuine = tk.BooleanVar(value=self.policy_store.settings.spoof_genuine_status)
        self.var_optin = tk.BooleanVar(value=self.policy_store.settings.analytics_opt_in)
        self.var_internet = tk.BooleanVar(value=self.policy_store.settings.can_access_internet)

        cb_bp = tk.Checkbutton(
            card,
            text="Bypass Cartridge Auth / DRM",
            variable=self.var_bypass_auth,
            command=self._on_bypass_toggle,
            bg=self.COLOR_CARD,
            font=("Segoe UI", 9, "bold"),
            fg="#7C3AED",
            activebackground=self.COLOR_CARD
        )
        cb_bp.pack(anchor="w", pady=2)

        cb_sp = tk.Checkbutton(
            card,
            text="Spoof Genuine OEM to Apps",
            variable=self.var_spoof_genuine,
            command=self._on_bypass_toggle,
            bg=self.COLOR_CARD,
            font=("Segoe UI", 9),
            activebackground=self.COLOR_CARD
        )
        cb_sp.pack(anchor="w", pady=2)

        cb1 = tk.Checkbutton(card, text="Analytics Opt-In (Telemetry)", variable=self.var_optin, bg=self.COLOR_CARD, font=("Segoe UI", 9), activebackground=self.COLOR_CARD)
        cb1.pack(anchor="w", pady=2)

        cb2 = tk.Checkbutton(card, text="Allow Internet Access", variable=self.var_internet, bg=self.COLOR_CARD, font=("Segoe UI", 9), activebackground=self.COLOR_CARD)
        cb2.pack(anchor="w", pady=2)

        # Firmware Update Setting
        tk.Label(card, text="Firmware Updates:", font=("Segoe UI", 9), fg=self.COLOR_MUTED, bg=self.COLOR_CARD).pack(anchor="w", pady=(6, 2))
        self.fw_combo = ttk.Combobox(card, values=["Never", "Notify", "Auto"], state="readonly", font=("Segoe UI", 9))
        self.fw_combo.set(self.policy_store.settings.fw_update_setting)
        self.fw_combo.pack(fill="x", pady=(0, 8))

        # Save Button
        ttk.Button(card, text="💾 Save Policies to settings.ini", style="Secondary.TButton", command=self._save_policies).pack(fill="x", pady=(2, 8))

        # Device Profile GUID Info
        dev_box = tk.Frame(card, bg="#F8FAFC", bd=1, relief="solid", padx=8, pady=4)
        dev_box.pack(fill="x", pady=(2, 0))
        tk.Label(dev_box, text="Hardware Profile:", font=("Segoe UI", 8, "bold"), fg=self.COLOR_MUTED, bg="#F8FAFC").pack(anchor="w")
        tk.Label(dev_box, text=DEFAULT_PRODUCT_GUID, font=("Consolas", 7), fg=self.COLOR_TEXT, bg="#F8FAFC").pack(anchor="w")

    def _build_bottom_card(self):
        bottom_frame = tk.Frame(self, bg=self.COLOR_CARD, height=180)
        bottom_frame.pack(fill="x", side="bottom", padx=20, pady=(0, 15))
        bottom_frame.pack_propagate(False)

        top_row = tk.Frame(bottom_frame, bg=self.COLOR_CARD)
        top_row.pack(fill="x", padx=15, pady=(10, 5))

        tk.Label(top_row, text="⚙️ Background Monitoring Daemon (hpqDTSS pattern)", font=("Segoe UI", 10, "bold"), fg=self.COLOR_TEXT, bg=self.COLOR_CARD).pack(side="left")

        self.btn_service = ttk.Button(top_row, text="▶ Start Service", style="Primary.TButton", command=self._toggle_service)
        self.btn_service.pack(side="right")

        self.lbl_service_state = tk.Label(top_row, text="Status: Stopped", font=("Segoe UI", 9), fg=self.COLOR_MUTED, bg=self.COLOR_CARD)
        self.lbl_service_state.pack(side="right", padx=15)

        # Log View
        self.log_text = tk.Text(bottom_frame, bg="#0F172A", fg="#F8FAFC", font=("Consolas", 8), height=6, relief="flat", padx=10, pady=6)
        self.log_text.pack(fill="both", expand=True, padx=15, pady=(0, 10))
        self.log_text.insert("end", "[System] Application initialized. Waiting for commands...\n")

    def _log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.see("end")

    def _refresh_spooler(self):
        printers = self.spooler.enum_printers()
        names = [p["printer_name"] for p in printers]
        self.printer_combo["values"] = names
        if names:
            # Prefer HP DeskJet or default to first
            if PRODUCT_NAME in names:
                self.printer_combo.set(PRODUCT_NAME)
            else:
                self.printer_combo.set(names[0])
            self._on_printer_selected(None)
        else:
            self.lbl_perm_status.config(text="No printers installed", fg=self.COLOR_MUTED)
        self._log(f"Spooler refreshed. Found {len(names)} printers.")

    def _on_printer_selected(self, _):
        printer_name = self.printer_combo.get()
        if not printer_name:
            return

        has_perm, msg = self.spooler.verify_print_permission(printer_name)
        if has_perm:
            self.lbl_perm_status.config(text="✓ GRANTED (PRINTER_ACCESS_USE)", fg=self.COLOR_SUCCESS)
        else:
            self.lbl_perm_status.config(text=f"✗ DENIED ({msg})", fg=self.COLOR_DANGER)

        status_report = self.spooler.get_printer_status(printer_name)
        flags_str = ", ".join(status_report.status_flags)
        self.lbl_queue_details.config(
            text=f"Port: {status_report.port_name}\nDriver: {status_report.driver_name}\nJobs: {status_report.job_count} | Status: {flags_str}"
        )

        self._evaluate_global_status()

    def _on_bypass_toggle(self):
        bypass = self.var_bypass_auth.get()
        spoof = self.var_spoof_genuine.get()
        self.ledm_status.bypass_cartridge_auth = bypass
        self.ledm_status.spoof_genuine_status = spoof
        self.policy_store.settings.bypass_cartridge_auth = bypass
        self.policy_store.settings.spoof_genuine_status = spoof
        self._update_supplies_ui()
        self._evaluate_global_status()
        self._log(f"Cartridge bypass updated: Bypass={bypass}, SpoofGenuine={spoof}")

    def _evaluate_global_status(self):
        can_ledm, ledm_reason = self.ledm_status.can_print()
        printer_name = self.printer_combo.get()
        has_perm, _ = self.spooler.verify_print_permission(printer_name) if printer_name else (False, "")

        if can_ledm and has_perm:
            if self.ledm_status.bypass_cartridge_auth and (self.ledm_status.black_ink.is_blocked() or self.ledm_status.color_ink.is_blocked()):
                self.status_badge.config(text="● READY TO PRINT (AUTH BYPASS)", bg="#8B5CF6")
            else:
                self.status_badge.config(text="● READY TO PRINT", bg=self.COLOR_SUCCESS)
        else:
            reason = ledm_reason if not can_ledm else "Spooler Blocked"
            self.status_badge.config(text=f"● ATTENTION: {reason.upper()}", bg=self.COLOR_DANGER)

    def _refresh_all_data(self):
        self._refresh_spooler()
        self._update_supplies_ui()

    def _update_supplies_ui(self):
        # Update Auth Pill
        bypass_active = self.var_bypass_auth.get()
        if bypass_active:
            spoof_text = " + SPOOF GENUINE OEM" if self.var_spoof_genuine.get() else ""
            self.lbl_auth_pill.config(
                text=f"🛡️ CARTRIDGE AUTH BYPASS: ACTIVE{spoof_text}",
                bg="#8B5CF6",
                fg="#FFFFFF"
            )
        else:
            self.lbl_auth_pill.config(
                text="⚠️ CARTRIDGE AUTH: STRICT ENFORCEMENT",
                bg="#EF4444",
                fg="#FFFFFF"
            )

        # Black
        b_pct = self.ledm_status.black_ink.level_percent
        b_st = self.ledm_status.black_ink.status
        self.prog_black["value"] = b_pct
        if bypass_active and self.ledm_status.black_ink.is_blocked():
            self.lbl_black_pct.config(text=f"{b_pct}% - {b_st} (Auth Bypassed)", fg="#8B5CF6")
        else:
            self.lbl_black_pct.config(text=f"{b_pct}% - {b_st}", fg=self.COLOR_MUTED)

        # Color
        c_pct = self.ledm_status.color_ink.level_percent
        c_st = self.ledm_status.color_ink.status
        self.prog_color["value"] = c_pct
        if bypass_active and self.ledm_status.color_ink.is_blocked():
            self.lbl_color_pct.config(text=f"{c_pct}% - {c_st} (Auth Bypassed)", fg="#8B5CF6")
        else:
            self.lbl_color_pct.config(text=f"{c_pct}% - {c_st}", fg=self.COLOR_MUTED)

        # Tray
        tray_st = self.ledm_status.input_tray_state
        if tray_st == "Ready":
            self.lbl_tray_status.config(text="Ready (Plain paper loaded)", fg=self.COLOR_SUCCESS)
        elif tray_st == "PaperOut":
            self.lbl_tray_status.config(text="Paper Out (Load paper into Tray 1)", fg=self.COLOR_DANGER)
        elif tray_st == "PaperJam":
            self.lbl_tray_status.config(text="Paper Jam (Clear paper path)", fg=self.COLOR_DANGER)

        self._evaluate_global_status()

    def _sim_paper_out(self):
        self.ledm_status.input_tray_state = "PaperOut"
        self._update_supplies_ui()
        self._log("Simulated hardware event: Input Tray Paper Out")

    def _sim_low_ink(self):
        self.ledm_status.black_ink.level_percent = 0
        self.ledm_status.black_ink.status = "Empty"
        self.ledm_status.color_ink.level_percent = 0
        self.ledm_status.color_ink.status = "Empty"
        self._update_supplies_ui()
        self._log("Simulated hardware event: Cartridges Depleted (Empty)")

    def _sim_non_hp(self):
        self.ledm_status.black_ink.status = "NonHP"
        self.ledm_status.black_ink.is_genuine_hp = False
        self.ledm_status.black_ink.auth_state = "ThirdPartyNonHP"
        self.ledm_status.color_ink.status = "Refilled"
        self.ledm_status.color_ink.is_genuine_hp = False
        self.ledm_status.color_ink.auth_state = "Refilled"
        self._update_supplies_ui()
        self._log("Simulated hardware event: Inserted Non-HP / Refilled Third-Party Cartridges")

    def _sim_reset_ok(self):
        self.ledm_status.input_tray_state = "Ready"
        self.ledm_status.black_ink.level_percent = 85
        self.ledm_status.black_ink.status = "Ready"
        self.ledm_status.black_ink.is_genuine_hp = True
        self.ledm_status.black_ink.auth_state = "GenuineOEM"
        self.ledm_status.color_ink.level_percent = 90
        self.ledm_status.color_ink.status = "Ready"
        self.ledm_status.color_ink.is_genuine_hp = True
        self.ledm_status.color_ink.auth_state = "GenuineOEM"
        self._update_supplies_ui()
        self._log("Simulated hardware event: Restored Genuine OEM Ready State")

    def _save_policies(self):
        self.policy_store.settings.analytics_opt_in = self.var_optin.get()
        self.policy_store.settings.can_access_internet = self.var_internet.get()
        self.policy_store.settings.fw_update_setting = self.fw_combo.get()
        self.policy_store.settings.bypass_cartridge_auth = self.var_bypass_auth.get()
        self.policy_store.settings.spoof_genuine_status = self.var_spoof_genuine.get()
        self.policy_store.save()
        self._log(f"Policies saved to settings.ini (BypassAuth={self.var_bypass_auth.get()}, SpoofGenuine={self.var_spoof_genuine.get()})")
        messagebox.showinfo("Policies Saved", "System policies successfully saved to settings.ini.")

    def _send_test_print(self):
        printer_name = self.printer_combo.get()
        if not printer_name:
            messagebox.showwarning("No Printer", "Please select a printer first.")
            return

        can_print, reason = self.ledm_status.can_print()
        if not can_print:
            messagebox.showerror("Print Blocked", f"Hardware is not ready to print: {reason}")
            return

        # Generate PCL3 raster
        self._log(f"Synthesizing HP PCL3 raster stream for '{printer_name}'...")
        pcl3_bytes = PCL3RasterGenerator.generate_test_pattern(width_dots=300, height_dots=100)
        self._log(f"Generated {len(pcl3_bytes)} bytes of PCL3 stream (ESC *v7S, ESC *r1A, ESC *b...W).")

        # Spool to printer
        ok, msg = self.spooler.submit_raw_print_job(printer_name, "PCL3 Diagnostic Print", pcl3_bytes)
        if ok:
            self._log(f"Print job spooled: {msg}")
            messagebox.showinfo("Print Job Spooled", f"Success!\n\n{msg}")
        else:
            self._log(f"Spooler error: {msg}")
            messagebox.showerror("Spool Failed", f"Failed to spool job:\n{msg}")

    def _toggle_service(self):
        if not self.service_running:
            printer_name = self.printer_combo.get() or PRODUCT_NAME
            self.monitor_service = DeviceMonitorService(self.data_dir, target_printer=printer_name, poll_interval_sec=2.0)
            self.monitor_service.start(run_in_background=True)
            self.service_running = True
            self.btn_service.config(text="⏹ Stop Service")
            self.lbl_service_state.config(text="Status: Running (Polling every 2s)", fg=self.COLOR_SUCCESS)
            self._log(f"Background monitoring service started for '{printer_name}'.")

            # Start GUI poller for service updates
            self._poll_service_state()
        else:
            if self.monitor_service:
                self.monitor_service.stop()
            self.service_running = False
            self.btn_service.config(text="▶ Start Service")
            self.lbl_service_state.config(text="Status: Stopped", fg=self.COLOR_MUTED)
            self._log("Background monitoring service stopped.")

    def _poll_service_state(self):
        if not self.service_running:
            return
        state_file = self.data_dir / "device_state.json"
        if state_file.exists():
            try:
                import json
                with open(state_file, "r") as f:
                    data = json.load(f)
                    telemetry = data.get("telemetry_event", "N/A")
                    self._log(f"[Daemon Poll] Ready: {data.get('overall_ready_to_print')} | Telemetry Gate: {telemetry}")
            except Exception:
                pass
        self.after(3000, self._poll_service_state)


if __name__ == "__main__":
    app = PrinterAssistantApp()
    app.mainloop()
