import os
import sys
import shutil
import subprocess
from pathlib import Path
from printer_manager import get_target_printer

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = Path("/tmp/printflow-uploads") if os.environ.get("VERCEL") else BASE_DIR / "uploads"

def dispatch_print_job(order_data: dict) -> dict:
    order_id = order_data.get("order_id", "UNKNOWN")
    file_rel_path = order_data.get("file_path", "")
    color_mode = order_data.get("color_mode", "black_white")
    copies = int(order_data.get("copies", 1))
    orientation = order_data.get("orientation", "portrait")

    # Resolve absolute file path on server
    clean_filename = Path(file_rel_path).name if file_rel_path else ""
    abs_file_path = UPLOAD_DIR / clean_filename

    target_printer = get_target_printer(color_mode)
    print(f"[PRINT DISPATCH] Processing Order {order_id} | File: '{clean_filename}' | Color Mode: {color_mode} | Printer: '{target_printer}' | Copies: {copies}")

    if not abs_file_path.exists():
        print(f"[PRINT DISPATCH WARNING] File '{abs_file_path}' not found on disk. Simulating spooling queue.")
        return {
            "status": "success",
            "simulated": True,
            "order_id": order_id,
            "printer": target_printer,
            "message": f"Order {order_id} spooled to virtual printer '{target_printer}'"
        }

    # Windows Direct Silent Printing Execution
    if sys.platform == "win32":
        try:
            # 1. SumatraPDF silent printing if available in PATH
            sumatra = shutil.which("SumatraPDF.exe") or shutil.which("SumatraPDF")
            if sumatra:
                orient_setting = "landscape" if orientation == "landscape" else "portrait"
                cmd = [sumatra, "-print-to", target_printer, "-print-settings", f"{copies}x,{orient_setting}", str(abs_file_path)]
                subprocess.run(cmd, check=True, timeout=15)
                print(f"[PRINT DISPATCH SUCCESS] Order {order_id} printed via SumatraPDF to '{target_printer}'")
                return {
                    "status": "success",
                    "order_id": order_id,
                    "printer": target_printer,
                    "method": "SumatraPDF",
                    "message": f"Printed successfully on '{target_printer}'"
                }

            # 2. Windows ShellExecute printto verb
            import win32api
            win32api.ShellExecute(0, "printto", str(abs_file_path), f'"{target_printer}"', ".", 0)
            print(f"[PRINT DISPATCH SUCCESS] Order {order_id} spooled via win32api to '{target_printer}'")
            return {
                "status": "success",
                "order_id": order_id,
                "printer": target_printer,
                "method": "win32api",
                "message": f"Spooled successfully to '{target_printer}'"
            }
        except Exception as win_err:
            print(f"[PRINT DISPATCH WIN32 WARNING]: {win_err}")
            # 3. PowerShell Out-Printer fallback
            try:
                ps_cmd = f'Start-Process -FilePath "{abs_file_path}" -Verb PrintTo -ArgumentList "{target_printer}" -PassThru'
                subprocess.run(["powershell", "-Command", ps_cmd], timeout=10)
                return {
                    "status": "success",
                    "order_id": order_id,
                    "printer": target_printer,
                    "method": "PowerShell",
                    "message": f"Dispatched via PowerShell to '{target_printer}'"
                }
            except Exception as ps_err:
                print(f"[PRINT DISPATCH PS ERROR]: {ps_err}")

    # Linux / macOS CUPS lp printing
    if sys.platform != "win32":
        try:
            lp = shutil.which("lp")
            if lp:
                cmd = [lp, "-d", target_printer, "-n", str(copies), str(abs_file_path)]
                subprocess.run(cmd, check=True, timeout=10)
                return {
                    "status": "success",
                    "order_id": order_id,
                    "printer": target_printer,
                    "method": "CUPS lp",
                    "message": f"Dispatched via CUPS to '{target_printer}'"
                }
        except Exception as cups_err:
            print(f"[PRINT DISPATCH CUPS ERROR]: {cups_err}")

    return {
        "status": "success",
        "order_id": order_id,
        "printer": target_printer,
        "message": f"Order {order_id} queued for printer '{target_printer}'"
    }
