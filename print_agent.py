import os
import sys
import json
import time
import shutil
import urllib.request
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "agent_config.json"
EXAMPLE_CONFIG_FILE = BASE_DIR / "agent_config.example.json"
TEMP_DOWNLOAD_DIR = BASE_DIR / "agent_temp"
TEMP_DOWNLOAD_DIR.mkdir(exist_ok=True)

def load_agent_config():
    if not CONFIG_FILE.exists():
        if EXAMPLE_CONFIG_FILE.exists():
            shutil.copy(EXAMPLE_CONFIG_FILE, CONFIG_FILE)
        else:
            default_data = {
                "backend_url": "https://print-flow-mu.vercel.app",
                "agent_token": "PF_AGENT_SECRET_TOKEN_2026",
                "poll_interval_seconds": 3,
                "bw_printer": "",
                "color_printer": "",
                "auto_routing": True
            }
            CONFIG_FILE.write_text(json.dumps(default_data, indent=2), encoding="utf-8")

    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as err:
        print("[AGENT CONFIG ERROR]:", err)
        return {
            "backend_url": "http://127.0.0.1:8000",
            "agent_token": "PF_AGENT_SECRET_TOKEN_2026",
            "poll_interval_seconds": 3
        }

def get_installed_windows_printers():
    printers = []
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
        except Exception as e:
            print("[AGENT PRINTER DISCOVERY WARNING]:", e)

    if not printers:
        printers.append({
            "name": "Microsoft Print to PDF",
            "driver": "Virtual",
            "status": "Normal",
            "is_default": True
        })
    return printers

def select_target_printer(color_mode: str, config: dict, installed_printers: list) -> str:
    printer_names = [p["name"] for p in installed_printers]
    default_printer = next((p["name"] for p in installed_printers if p.get("is_default")), printer_names[0])

    if color_mode.lower() in ("color", "colour"):
        target = config.get("color_printer", "").strip()
        if not target:
            target = next((n for n in printer_names if "color" in n.lower()), "")
    else:
        target = config.get("bw_printer", "").strip()
        if not target:
            target = next((n for n in printer_names if any(k in n.lower() for k in ("b&w", "mono", "black", "laser"))), "")

    if not target or target not in printer_names:
        target = default_printer

    return target

def download_file(backend_url: str, file_rel_path: str) -> Path:
    filename = Path(file_rel_path).name
    target_path = TEMP_DOWNLOAD_DIR / filename
    full_url = f"{backend_url.rstrip('/')}{file_rel_path if file_rel_path.startswith('/') else '/' + file_rel_path}"

    req = urllib.request.Request(full_url, headers={"User-Agent": "PrintFlowAgent/1.0"})
    with urllib.request.urlopen(req, timeout=30) as response, target_path.open("wb") as out_file:
        shutil.copyfileobj(response, out_file)

    return target_path

def print_document_silently(file_path: Path, printer_name: str, copies: int = 1, orientation: str = "portrait"):
    ext = file_path.suffix.lower()
    print(f"[AGENT SILENT PRINT] Printing '{file_path.name}' ({ext}) to '{printer_name}' | Copies: {copies} | Orient: {orientation}")

    if sys.platform != "win32":
        # Linux/macOS CUPS silent print
        lp = shutil.which("lp")
        if lp:
            cmd = [lp, "-d", printer_name, "-n", str(copies), str(file_path)]
            subprocess.run(cmd, check=True, timeout=15)
            return True
        return True

    # Windows Printing Logic
    # 1. PDF via SumatraPDF
    if ext == ".pdf":
        sumatra = shutil.which("SumatraPDF.exe") or shutil.which("SumatraPDF")
        if sumatra:
            orient_opt = "landscape" if orientation == "landscape" else "portrait"
            cmd = [sumatra, "-print-to", printer_name, "-print-settings", f"{copies}x,{orient_opt}", str(file_path)]
            subprocess.run(cmd, check=True, timeout=20)
            return True

    # 2. DOC / DOCX via Word/WordPad COM Automation or PowerShell
    if ext in (".doc", ".docx"):
        try:
            import win32com.client
            word = win32com.client.Dispatch("Word.Application")
            word.Visible = False
            doc = word.Documents.Open(str(file_path))
            word.ActivePrinter = printer_name
            doc.PrintOut(Copies=copies)
            doc.Close(False)
            word.Quit()
            return True
        except Exception as word_err:
            print("[AGENT WORD COM WARNING]:", word_err)

    # 3. Native Windows ShellExecute printto verb (PNG, JPG, WEBP, TXT, PDF, DOC)
    try:
        import win32api
        for _ in range(copies):
            win32api.ShellExecute(0, "printto", str(file_path), f'"{printer_name}"', ".", 0)
            time.sleep(0.5)
        return True
    except Exception as win_err:
        print("[AGENT WIN32 SHELL WARNING]:", win_err)

    # 4. PowerShell Out-Printer / Start-Process fallback
    ps_cmd = f'Start-Process -FilePath "{str(file_path)}" -Verb PrintTo -ArgumentList "{printer_name}" -WindowStyle Hidden -PassThru'
    subprocess.run(["powershell", "-Command", ps_cmd], check=True, timeout=15)
    return True

def run_agent():
    print("==================================================")
    print("  🖨️  PrintFlow Local Windows Print Agent v1.0   ")
    print("==================================================")

    config = load_agent_config()
    backend_url = config.get("backend_url", "https://print-flow-mu.vercel.app").rstrip("/")
    agent_token = (os.environ.get("PRINT_AGENT_TOKEN") or config.get("agent_token", "PF_AGENT_SECRET_TOKEN_2026")).strip()
    poll_interval = int(config.get("poll_interval_seconds", 3))

    # Perform safe startup cleanup of any orphaned temporary files
    if TEMP_DOWNLOAD_DIR.exists():
        for item in TEMP_DOWNLOAD_DIR.glob("*"):
            if item.is_file():
                try:
                    item.unlink()
                    print(f"[AGENT STARTUP CLEANUP] Removed orphaned temporary file: {item.name}")
                except Exception:
                    pass

    print(f" Target Backend: {backend_url}")
    print(f" Poll Interval : {poll_interval} seconds")
    print(" Agent Status   : STARTING...\n")

    while True:
        try:
            installed_printers = get_installed_windows_printers()

            # 1. Heartbeat & Poll Queue from Backend
            poll_url = f"{backend_url}/api/agent/poll"
            req_data = json.dumps({
                "printers": installed_printers,
                "status": "ONLINE"
            }).encode("utf-8")

            req = urllib.request.Request(
                poll_url,
                data=req_data,
                headers={
                    "Content-Type": "application/json",
                    "X-Print-Agent-Token": agent_token,
                    "User-Agent": "PrintFlowAgent/1.0"
                },
                method="POST"
            )

            with urllib.request.urlopen(req, timeout=10) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))

            queued_jobs = resp_data.get("jobs", [])
            if queued_jobs:
                print(f"[AGENT POLL] Found {len(queued_jobs)} pending print job(s) in queue!")

            for job in queued_jobs:
                order_id = job.get("order_id")
                file_rel_path = job.get("file_path")
                color_mode = job.get("color_mode", "black_white")
                copies = int(job.get("copies", 1))
                orientation = job.get("orientation", "portrait")

                if not order_id or not file_rel_path:
                    continue

                # 2. Claim Job Atomically from Backend
                claim_url = f"{backend_url}/api/agent/claim/{order_id}"
                claim_req = urllib.request.Request(
                    claim_url,
                    headers={
                        "X-Print-Agent-Token": agent_token,
                        "User-Agent": "PrintFlowAgent/1.0"
                    },
                    method="POST"
                )

                try:
                    with urllib.request.urlopen(claim_req, timeout=10) as claim_resp:
                        claim_res = json.loads(claim_resp.read().decode("utf-8"))
                        if claim_res.get("status") != "success":
                            print(f"[AGENT CLAIM REJECTED] Order {order_id} already claimed by another worker.")
                            continue
                except Exception as claim_err:
                    print(f"[AGENT CLAIM ERROR] Skipping order {order_id}:", claim_err)
                    continue

                print(f"[AGENT CLAIMED ORDER] Order ID: {order_id} | State: PRINTING")

                # 3. Download Document File & Select Target Printer
                target_printer = select_target_printer(color_mode, config, installed_printers)
                try:
                    local_file = download_file(backend_url, file_rel_path)
                    print(f"[AGENT FILE DOWNLOADED] File: {local_file.name}")

                    # 4. Execute Silent Direct Print
                    print_document_silently(local_file, target_printer, copies, orientation)

                    # 5. Notify Backend of Completion
                    complete_url = f"{backend_url}/api/agent/complete/{order_id}"
                    comp_data = json.dumps({
                        "status": "COMPLETED",
                        "printed_by_printer": target_printer
                    }).encode("utf-8")

                    comp_req = urllib.request.Request(
                        complete_url,
                        data=comp_data,
                        headers={
                            "Content-Type": "application/json",
                            "X-Print-Agent-Token": agent_token,
                            "User-Agent": "PrintFlowAgent/1.0"
                        },
                        method="POST"
                    )
                    with urllib.request.urlopen(comp_req, timeout=10) as comp_resp:
                        print(f"[AGENT JOB COMPLETED] Order {order_id} marked COMPLETED on backend!")

                    # 6. Wait 2.5 seconds & securely delete local downloaded copy
                    time.sleep(2.5)
                    if local_file.exists() and local_file.is_file():
                        try:
                            local_file.unlink()
                            print(f"[AGENT LOCAL PRIVACY CLEANUP] Local temp file '{local_file.name}' deleted 2.5s after printing.")
                        except Exception as c_err:
                            print(f"[AGENT LOCAL CLEANUP ERROR]: {c_err}")

                except Exception as print_err:
                    print(f"[AGENT PRINT ERROR] Order {order_id} printing failed: {print_err}")
                    # Notify Backend of Failure
                    fail_url = f"{backend_url}/api/agent/complete/{order_id}"
                    fail_data = json.dumps({
                        "status": "FAILED",
                        "error": str(print_err),
                        "printed_by_printer": target_printer
                    }).encode("utf-8")

                    fail_req = urllib.request.Request(
                        fail_url,
                        data=fail_data,
                        headers={
                            "Content-Type": "application/json",
                            "X-Print-Agent-Token": agent_token,
                            "User-Agent": "PrintFlowAgent/1.0"
                        },
                        method="POST"
                    )
                    try:
                        with urllib.request.urlopen(fail_req, timeout=10):
                            pass
                    except Exception:
                        pass

        except Exception as poll_err:
            pass

        time.sleep(poll_interval)

if __name__ == "__main__":
    run_agent()
