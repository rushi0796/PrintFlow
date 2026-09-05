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

def download_file(backend_url: str, file_rel_path: str, agent_token: str = "", original_file_name: str = "") -> Path:
    filename = Path(original_file_name or Path(file_rel_path).name).name
    target_path = TEMP_DOWNLOAD_DIR / filename
    full_url = f"{backend_url.rstrip('/')}{file_rel_path if file_rel_path.startswith('/') else '/' + file_rel_path}"

    req = urllib.request.Request(full_url, headers={"User-Agent": "PrintFlowAgent/1.0", "X-Print-Agent-Token": agent_token})
    with urllib.request.urlopen(req, timeout=30) as response, target_path.open("wb") as out_file:
        shutil.copyfileobj(response, out_file)

    return target_path

def create_n_up_pdf(input_pdf_path: Path, pages_per_sheet: int, page_order: str = "horizontal") -> Path:
    if pages_per_sheet <= 1:
        return input_pdf_path

    try:
        import pypdf
        reader = pypdf.PdfReader(str(input_pdf_path))
        num_pages = len(reader.pages)
        if num_pages == 0:
            return input_pdf_path

        writer = pypdf.PdfWriter()

        if pages_per_sheet == 2:
            cols, rows = 1, 2
        elif pages_per_sheet == 4:
            cols, rows = 2, 2
        elif pages_per_sheet == 6:
            cols, rows = 2, 3
        elif pages_per_sheet == 9:
            cols, rows = 3, 3
        elif pages_per_sheet == 16:
            cols, rows = 4, 4
        else:
            cols, rows = 1, 1

        sheet_w, sheet_h = 595.0, 842.0
        cell_w = sheet_w / cols
        cell_h = sheet_h / rows

        i = 0
        while i < num_pages:
            blank_page = writer.add_blank_page(width=sheet_w, height=sheet_h)
            for r in range(rows):
                for c in range(cols):
                    idx = i + (c * rows + r) if page_order == "vertical" else i + (r * cols + c)
                    if idx < num_pages:
                        src_page = reader.pages[idx]
                        orig_w = float(src_page.mediabox.width)
                        orig_h = float(src_page.mediabox.height)

                        scale = min(cell_w / orig_w, cell_h / orig_h) * 0.95
                        scaled_w = orig_w * scale
                        scaled_h = orig_h * scale

                        tx = c * cell_w + (cell_w - scaled_w) / 2.0
                        ty = sheet_h - ((r + 1) * cell_h) + (cell_h - scaled_h) / 2.0

                        blank_page.merge_scaled_page(src_page, scale, tx=tx, ty=ty)
            i += pages_per_sheet

        output_path = input_pdf_path.parent / f"nup_{pages_per_sheet}_{input_pdf_path.name}"
        with open(output_path, "wb") as f_out:
            writer.write(f_out)
        return output_path
    except Exception as nup_err:
        print("[MICRO XEROX N-UP WARNING]:", nup_err)
        return input_pdf_path

def print_document_silently(
    file_path: Path,
    printer_name: str,
    copies: int = 1,
    orientation: str = "portrait",
    color_mode: str = "black_white",
    duplex: str = "single",
    paper_size: str = "a4",
    scale_mode: str = "fit",
    pages_per_sheet: int = 1,
    page_order: str = "horizontal"
):
    ext = file_path.suffix.lower()
    print(f"[AGENT SILENT PRINT] File: '{file_path.name}' | Printer: '{printer_name}' | Copies: {copies} | Orient: {orientation} | Duplex: {duplex} | Paper: {paper_size} | Scale: {scale_mode}")

    target_print_file = file_path
    if ext == ".pdf" and pages_per_sheet > 1:
        target_print_file = create_n_up_pdf(file_path, pages_per_sheet, page_order)

    if sys.platform != "win32":
        lp = shutil.which("lp")
        if lp:
            cmd = [lp, "-d", printer_name, "-n", str(copies), str(target_print_file)]
            subprocess.run(cmd, check=True, timeout=15)
            return True
        return True

    if ext == ".pdf":
        sumatra = shutil.which("SumatraPDF.exe") or shutil.which("SumatraPDF")
        if sumatra:
            settings_parts = []
            
            if scale_mode != "actual":
                settings_parts.append("fit")
            
            if duplex in ("double", "duplex", "duplexlong"):
                settings_parts.append("duplexlong")
            elif duplex in ("duplexshort", "short"):
                settings_parts.append("duplexshort")
            else:
                settings_parts.append("noduplex")

            if orientation == "landscape":
                settings_parts.append("landscape")
            else:
                settings_parts.append("portrait")

            if paper_size:
                settings_parts.append(f"paper={paper_size.lower()}")

            settings_parts.append(f"{copies}x")

            if color_mode.lower() in ("color", "colour"):
                settings_parts.append("color")
            else:
                settings_parts.append("monochrome")

            settings_str = ",".join(settings_parts)
            cmd = [sumatra, "-print-to", printer_name, "-print-settings", settings_str, str(target_print_file)]
            print(f"[SUMATRAPDF EXECUTE] Command: {' '.join(cmd)}")
            subprocess.run(cmd, check=True, timeout=25)
            return True

    if ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
        try:
            import win32ui
            from PIL import Image, ImageWin
            img = Image.open(target_print_file)
            hdc = win32ui.CreateDC()
            hdc.CreatePrinterDC(printer_name)
            printable_width = hdc.GetDeviceCaps(8)
            printable_height = hdc.GetDeviceCaps(10)
            for _ in range(copies):
                hdc.StartDoc(f"PrintFlow - {target_print_file.name}")
                hdc.StartPage()
                img_w, img_h = img.size
                scale = min(printable_width / img_w, printable_height / img_h)
                new_w = int(img_w * scale)
                new_h = int(img_h * scale)
                x = (printable_width - new_w) // 2
                y = (printable_height - new_h) // 2
                dib = ImageWin.Dib(img)
                dib.draw(hdc.GetHandleOutput(), (x, y, x + new_w, y + new_h))
                hdc.EndPage()
                hdc.EndDoc()
            return True
        except Exception as img_err:
            print("[AGENT GDI IMAGE PRINT WARNING]:", img_err)

    if ext in (".doc", ".docx"):
        try:
            import win32com.client
            word = win32com.client.Dispatch("Word.Application")
            word.Visible = False
            doc = word.Documents.Open(str(target_print_file))
            word.ActivePrinter = printer_name
            doc.PrintOut(Copies=copies)
            doc.Close(False)
            word.Quit()
            return True
        except Exception as word_err:
            print("[AGENT WORD COM WARNING]:", word_err)

    try:
        import win32api
        for _ in range(copies):
            win32api.ShellExecute(0, "printto", str(target_print_file), f'"{printer_name}"', ".", 0)
            time.sleep(0.5)
        return True
    except Exception as win_err:
        print("[AGENT WIN32 SHELL WARNING]:", win_err)

    ps_cmd = f'Start-Process -FilePath "{str(target_print_file)}" -Verb PrintTo -ArgumentList "{printer_name}" -WindowStyle Hidden -PassThru'
    subprocess.run(["powershell", "-Command", ps_cmd], check=True, timeout=15)
    return True

def run_agent():
    print("==================================================")
    print("  [PRINTFLOW] Local Windows Print Agent v1.0      ")
    print("==================================================")

    config = load_agent_config()
    backend_url = config.get("backend_url", "https://print-flow-mu.vercel.app").rstrip("/")
    agent_token = (os.environ.get("PRINT_AGENT_TOKEN") or config.get("agent_token", "PF_AGENT_SECRET_TOKEN_2026")).strip()
    poll_interval = int(config.get("poll_interval_seconds", 3))

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
                duplex = job.get("duplex", "single")
                paper_size = job.get("paper_size", "a4")
                orientation = job.get("orientation", "portrait")
                scale_mode = job.get("scale_mode", "fit")
                pages_per_sheet = int(job.get("pages_per_sheet", 1))
                page_order = job.get("page_order", "horizontal")

                if not order_id or not file_rel_path:
                    continue

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

                target_printer = select_target_printer(color_mode, config, installed_printers)
                try:
                    local_file = download_file(backend_url, file_rel_path, agent_token, job.get("file_name", ""))
                    print(f"[AGENT FILE DOWNLOADED] File: {local_file.name}")

                    print_document_silently(
                        local_file,
                        target_printer,
                        copies=copies,
                        orientation=orientation,
                        color_mode=color_mode,
                        duplex=duplex,
                        paper_size=paper_size,
                        scale_mode=scale_mode,
                        pages_per_sheet=pages_per_sheet,
                        page_order=page_order
                    )

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

                    time.sleep(2.5)
                    if local_file.exists() and local_file.is_file():
                        try:
                            local_file.unlink()
                            print(f"[AGENT LOCAL PRIVACY CLEANUP] Local temp file '{local_file.name}' deleted 2.5s after printing.")
                        except Exception as c_err:
                            print(f"[AGENT LOCAL CLEANUP ERROR]: {c_err}")

                except Exception as print_err:
                    print(f"[AGENT PRINT ERROR] Order {order_id} printing failed: {print_err}")
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

        except Exception:
            pass

        time.sleep(poll_interval)

if __name__ == "__main__":
    run_agent()
