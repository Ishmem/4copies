# HP DeskJet 2130 System Architecture & Device Spooler Manager

A production-grade, clean-room implementation of the device management, policy enforcement, and print spooling architecture reverse-engineered from **HP NextGen Device Software** (`HP DeskJet 2130 series`).

---

## 1. System Architecture Overview

The system decomposes the HP printer software stack into four coordinated layers and a continuous background monitoring service:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        OPERATOR & APPLICATION LAYER                    │
│           CLI Management Utility (cli.py) & Applications               │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        BACKGROUND DAEMON LAYER                         │
│   DeviceMonitorService (services/device_monitor_service.py)           │
│   • Periodically polls print queues & hardware readiness               │
│   • Enforces settings.ini privacy gates & syncs device_state.json      │
│   • Gated PDSMQ telemetry dispatch                                     │
└──────────────┬────────────────────┬────────────────────┬───────────────┘
               │                    │                    │
               ▼                    ▼                    ▼
┌──────────────────────┐ ┌──────────────────────┐ ┌──────────────────────┐
│     POLICY STORE     │ │   DEVICE REGISTRY    │ │   LEDM XML CLIENT    │
│    (settings.ini)    │ │     ({GUID}.ini)     │ │ (hpygidDataMap.xml)  │
│  Privacy & Updates   │ │   DriverStore Paths  │ │ Ink & Tray Status    │
└──────────────────────┘ └──────────────────────┘ └──────────────────────┘
               │                                         │
               └────────────────────┬────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        WINDOWS PRINT & SPOOLER                         │
│   • SpoolerManager (winspool.drv via ctypes)                           │
│   • Verifies PRINTER_ACCESS_USE permissions                            │
│   • PCL3RasterGenerator: ESC *v7S, ESC *r1A, ESC *b...W               │
│   • Direct RAW spooling to \\.\USBPRINT / Spooler Queues               │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Implemented Subsystems

### A. Policy Store (`hp_device_manager/policy_store.py`)
- Reads, type-casts, validates, and atomically writes `settings.ini`.
- Manages multi-section policy configurations:
  - `[Analytics] OptIn=false`
  - `[FWUpdate] FWUpdateSetting=Never`
  - `[InternetPermissions] CanAccessInternet=Yes, PromptBeforeAccess=No`
  - `[UsageTracking] UTSettings=No`
- Provides strict boolean gating functions (`is_telemetry_allowed()`).

### B. Device Instance Registry (`hp_device_manager/device_registry.py`)
- Manages `{GUID}.ini` hardware profiles (e.g. `{D82824A3-7576-4820-B68A-BB92F2ED1EDF}.ini`).
- Stores mapping between device GUID, USB Vendor/Product ID (`Vid_03F0&Pid_E111`), Hardware ID (`HPDeskJet_2130_serie56EE`), and active Windows `DriverStore` repository locations.

### C. LEDM Protocol Client (`hp_device_manager/ledm_protocol.py`)
- Implements HP's **Low-End Data Model (LEDM)** RESTful XML protocol as uncovered in `hpygidDataMap.xml`.
- Communicates across USB endpoints `mi_02` (WinUSB) and `mi_03` (REST) to inspect cartridge levels, ink status, and paper tray conditions.

### D. HP PCL3 / PCL3GUI Command Generator (`hp_device_manager/pcl3_raster.py`)
- Constructs raw PCL3GUI print streams matching specifications from `hpdj_2130.gpd`:
  - `CmdBeginRaster`: `<1B>*v7S<1B>*r1A` (Color plane init & raster start)
  - `CmdSendBlockData`: `<1B>*b<length>W<data>` (Raster strip data transfer)
  - `CmdEndRaster`: `<1B>*rC` (End raster session)
  - `CmdFF`: `<0C>` (Form Feed)

### E. Windows Spooler Manager (`hp_device_manager/spooler_manager.py`)
- Integrates directly with Windows `winspool.drv` using `ctypes` without external dependencies.
- Features:
  - `verify_print_permission()`: Verifies if the user holds `PRINTER_ACCESS_USE`.
  - `get_printer_status()`: Unpacks `PRINTER_INFO_2` and identifies error states (`PAPER_JAM`, `PAPER_OUT`, `OFFLINE`, `DOOR_OPEN`).
  - `submit_raw_print_job()`: Dispatches raw PCL3 streams to the Spooler (`StartDocPrinterW`, `WritePrinter`).

### F. Background Monitoring Service (`services/device_monitor_service.py`)
- Continuous monitoring daemon (reproducing the role of `hpqDTSS.exe` and `HPNetworkCommunicatorCom.exe`).
- Synchronizes printer state to `runtime_data/device_state.json` for IPC with user-facing utilities.
- Implements graceful shutdown handlers (`SIGINT`/`SIGTERM`).

---

## 3. Quick Start & Desktop Application

### Launching the Desktop App
You can launch the desktop GUI app in any of these simple ways:
1. **Desktop Shortcut:** Double-click `HP DeskJet Assistant.bat` on your **Desktop**.
2. **From Terminal:**
   ```bash
   python app.py
   ```
3. **Workspace Launcher:** Double-click `run_app.bat` inside the project folder.

### Running the End-to-End Verification Demo
```bash
python demo.py
```

### Running the Test Suite
```bash
python -m unittest discover tests
```

### CLI Commands

1. **Audit print queues and permissions:**
   ```bash
   python cli.py status
   ```

2. **Read system policies:**
   ```bash
   python cli.py policy get
   ```

3. **Update system privacy policies:**
   ```bash
   python cli.py policy set --optin false --internet true --update-setting Never
   ```

4. **Register a hardware device instance:**
   ```bash
   python cli.py devices register --guid "{D82824A3-7576-4820-B68A-BB92F2ED1EDF}" --name "HP DeskJet 2130 series"
   ```

5. **Generate a PCL3 raster test pattern:**
   ```bash
   # Save raw PCL3 stream to file
   python cli.py print-test --output test_page.pcl3

   # Or submit directly to a Windows Spooler queue
   python cli.py print-test --printer "Microsoft Print to PDF"
   ```

6. **Run the background monitoring daemon:**
   ```bash
   python cli.py service --printer "HP DeskJet 2130 series" --interval 2.0
   ```
