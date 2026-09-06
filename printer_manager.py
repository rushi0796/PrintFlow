import os
import sys
import json
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "printer_config.json"
AGENT_CONFIG_FILE = BASE_DIR / "agent_config.json"

DEFAULT_CONFIG = {
    "bw_printer": "",
    "color_printer": "",
    "auto_routing": True
}

def get_printer_config():
    config = DEFAULT_CONFIG.copy()
    if AGENT_CONFIG_FILE.exists():
        try:
            agent_data = json.loads(AGENT_CONFIG_FILE.read_text(encoding="utf-8"))
            if agent_data.get("bw_printer"):
                config["bw_printer"] = agent_data["bw_printer"]
            if agent_data.get("color_printer"):
                config["color_printer"] = agent_data["color_printer"]
        except Exception:
            pass
    if CONFIG_FILE.exists():
        try:
            printer_data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            config.update(printer_data)
        except Exception:
            pass
    return config

def save_printer_config(config: dict):
    CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config

def get_installed_printers():
    printers = []

    # Windows PowerShell printer detection
    if sys.platform == "win32":
        try:
            ps_cmd = 'Get-Printer | Select-Object Name, DriverName, PrinterStatus, IsDefault | ConvertTo-Json'
            res = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, timeout=10)
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                if isinstance(data, dict):
                    data = [data]
                for p in data:
                    printers.append({
                        "name": p.get("Name", ""),
                        "driver": p.get("DriverName", ""),
                        "status": "Normal" if p.get("PrinterStatus") in (0, "Normal", None) else str(p.get("PrinterStatus")),
                        "is_default": bool(p.get("IsDefault"))
                    })
        except Exception as err:
            print("[PRINTER DETECT ERROR]:", err)

    # PyWin32 fallback for Windows
    if not printers and sys.platform == "win32":
        try:
            import win32print
            enum_printers = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)
            for p in enum_printers:
                name = p[2]
                printers.append({
                    "name": name,
                    "driver": "Generic",
                    "status": "Normal",
                    "is_default": name == win32print.GetDefaultPrinter()
                })
        except Exception:
            pass

    # Linux / macOS CUPS fallback
    if not printers and sys.platform != "win32":
        try:
            res = subprocess.run(["lpstat", "-p"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if line.startswith("printer"):
                        parts = line.split()
                        if len(parts) > 1:
                            printers.append({
                                "name": parts[1],
                                "driver": "CUPS",
                                "status": "Idle" if "idle" in line else "Active",
                                "is_default": False
                            })
        except Exception:
            pass

    # Fallback default printer placeholder if none detected
    if not printers:
        printers.append({
            "name": "Default System Printer",
            "driver": "Virtual",
            "status": "Ready",
            "is_default": True
        })

    return printers

def get_target_printer(color_mode: str = "black_white") -> str:
    config = get_printer_config()
    installed = get_installed_printers()
    installed_names = [p["name"] for p in installed]
    default_printer = next((p["name"] for p in installed if p.get("is_default")), installed[0]["name"])

    target_name = ""
    if color_mode.lower() in ("color", "colour"):
        target_name = config.get("color_printer", "").strip()
        # Auto-match if not explicitly configured
        if not target_name:
            target_name = next((name for name in installed_names if "color" in name.lower()), "")
    else:
        target_name = config.get("bw_printer", "").strip()
        # Auto-match if not explicitly configured
        if not target_name:
            target_name = next((name for name in installed_names if "b&w" in name.lower() or "mono" in name.lower() or "black" in name.lower()), "")

    if not target_name or target_name not in installed_names:
        target_name = default_printer

    return target_name
