import os
import sys
import json
import time
import shutil
import urllib.request
import subprocess
from pathlib import Path
from typing import Optional

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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
    raw_filename = Path(original_file_name or Path(file_rel_path).name).name
    clean_name = "".join(c for c in raw_filename if c.isalnum() or c in "._- ")
    if not clean_name.strip() or clean_name.startswith("."):
        clean_name = f"doc_{Path(file_rel_path).name}{Path(raw_filename).suffix or '.pdf'}"
    target_path = TEMP_DOWNLOAD_DIR / clean_name
    full_url = f"{backend_url.rstrip('/')}{file_rel_path if file_rel_path.startswith('/') else '/' + file_rel_path}"

    req = urllib.request.Request(full_url, headers={"User-Agent": "PrintFlowAgent/1.0", "X-Print-Agent-Token": agent_token})
    with urllib.request.urlopen(req, timeout=30) as response, target_path.open("wb") as out_file:
        shutil.copyfileobj(response, out_file)

    return target_path

def find_sumatra_executable() -> Optional[str]:
    candidates = [
        shutil.which("SumatraPDF.exe"),
        shutil.which("SumatraPDF"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "SumatraPDF" / "SumatraPDF.exe",
        Path("C:/Program Files/SumatraPDF/SumatraPDF.exe"),
        Path("C:/Program Files (x86)/SumatraPDF/SumatraPDF.exe"),
        Path(os.environ.get("APPDATA", "")) / "SumatraPDF" / "SumatraPDF.exe",
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return str(c)
    return None

def create_n_up_pdf(
    input_pdf_path: Path,
    pages_per_sheet: int,
    page_order: str = "horizontal",
    paper_size: str = "a4",
    orientation: str = "portrait"
) -> Path:
    if pages_per_sheet <= 1:
        return input_pdf_path

    try:
        import pypdf
        from pypdf import Transformation
        reader = pypdf.PdfReader(str(input_pdf_path))
        num_pages = len(reader.pages)
        if num_pages == 0:
            return input_pdf_path

        writer = pypdf.PdfWriter()

        grid_map = {
            2: (1, 2),
            4: (2, 2),
            6: (2, 3),
            9: (3, 3),
            16: (4, 4),
        }
        cols, rows = grid_map.get(pages_per_sheet, (1, 1))

        paper_dims = {
            "a4": (595.28, 841.89),
            "letter": (612.0, 792.0),
            "legal": (612.0, 1008.0)
        }
        pw, ph = paper_dims.get(paper_size.lower(), (595.28, 841.89))
        if orientation.lower() == "landscape":
            sheet_w, sheet_h = max(pw, ph), min(pw, ph)
            if pages_per_sheet == 2:
                cols, rows = 2, 1
            elif pages_per_sheet == 6:
                cols, rows = 3, 2
        else:
            sheet_w, sheet_h = min(pw, ph), max(pw, ph)
            if pages_per_sheet == 2:
                cols, rows = 1, 2
            elif pages_per_sheet == 6:
                cols, rows = 2, 3

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

                        op = Transformation().scale(scale, scale).translate(tx, ty)
                        blank_page.merge_transformed_page(src_page, op)
            i += pages_per_sheet

        output_path = input_pdf_path.parent / f"nup_{pages_per_sheet}_{input_pdf_path.name}"
        with open(output_path, "wb") as f_out:
            writer.write(f_out)
        return output_path
    except Exception as nup_err:
        print(f"[MICRO XEROX N-UP WARNING]: {nup_err}")
        return input_pdf_path

def get_page_content_bounds(page) -> Optional[tuple]:
    """
    Extracts the visual content bounding box (min_x, min_y, max_x, max_y)
    from text, images, and vector paths.
    """
    min_x, min_y, max_x, max_y = float('inf'), float('inf'), float('-inf'), float('-inf')

    def visitor_op(op, args, cm, tm):
        nonlocal min_x, min_y, max_x, max_y
        op_name = op.decode('ascii', errors='ignore') if isinstance(op, bytes) else str(op)

        if op_name in ('Tj', 'TJ'):
            txt = ''
            if args and isinstance(args[0], (bytes, str)):
                raw = args[0]
                txt = raw.decode('latin1', errors='ignore') if isinstance(raw, bytes) else raw
            elif args and isinstance(args[0], list):
                txt = ''.join(x.decode('latin1', errors='ignore') if isinstance(x, bytes) else (str(x) if isinstance(x, str) else '') for x in args[0])

            if txt.strip():
                x, y = tm[4], tm[5]
                tx, ty = cm[4], cm[5]
                sx = cm[0] if cm[0] != 0 else 1.0
                sy = cm[3] if cm[3] != 0 else 1.0
                fx = tx + x * sx
                fy = ty + y * sy
                fs = 12.0
                fw = len(txt.strip()) * fs * 0.55 * sx
                fh = fs * sy
                min_x = min(min_x, fx)
                min_y = min(min_y, fy - fh * 0.2)
                max_x = max(max_x, fx + fw)
                max_y = max(max_y, fy + fh)

        elif op_name == 'Do':
            w, h, x, y = abs(cm[0]), abs(cm[3]), cm[4], cm[5]
            if w > 5 and h > 5:
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x + w)
                max_y = max(max_y, y + h)

        elif op_name == 're' and len(args) == 4:
            try:
                rx, ry, rw, rh = float(args[0]), float(args[1]), float(args[2]), float(args[3])
                tx, ty = cm[4], cm[5]
                sx = cm[0] if cm[0] != 0 else 1.0
                sy = cm[3] if cm[3] != 0 else 1.0
                fx0 = tx + rx * sx
                fy0 = ty + ry * sy
                fx1 = fx0 + rw * sx
                fy1 = fy0 + rh * sy
                min_x = min(min_x, min(fx0, fx1))
                min_y = min(min_y, min(fy0, fy1))
                max_x = max(max_x, max(fx0, fx1))
                max_y = max(max_y, max(fy0, fy1))
            except Exception:
                pass

        elif op_name in ('m', 'l') and len(args) >= 2:
            try:
                px, py = float(args[0]), float(args[1])
                tx, ty = cm[4], cm[5]
                sx = cm[0] if cm[0] != 0 else 1.0
                sy = cm[3] if cm[3] != 0 else 1.0
                fx, fy = tx + px * sx, ty + py * sy
                min_x = min(min_x, fx)
                min_y = min(min_y, fy)
                max_x = max(max_x, fx)
                max_y = max(max_y, fy)
            except Exception:
                pass

    try:
        page.extract_text(visitor_operand_before=visitor_op)
    except Exception:
        pass

    if min_x != float('inf') and max_x > min_x and max_y > min_y:
        return (min_x, min_y, max_x, max_y)
    return None

def optimize_pdf_for_full_page(
    input_pdf_path: Path,
    paper_size: str = "a4",
    orientation: str = "portrait"
) -> Path:
    """
    Expands content proportionally towards the physical printable boundaries of the paper
    when 'Full Page' mode is selected, removing excessive document whitespace margins.
    """
    try:
        import pypdf
        from pypdf import Transformation

        reader = pypdf.PdfReader(str(input_pdf_path))
        num_pages = len(reader.pages)
        if num_pages == 0:
            return input_pdf_path

        paper_dims = {
            "a4": (595.28, 841.89),
            "letter": (612.0, 792.0),
            "legal": (612.0, 1008.0)
        }
        pw, ph = paper_dims.get(paper_size.lower(), (595.28, 841.89))
        if orientation.lower() == "landscape":
            sheet_w, sheet_h = max(pw, ph), min(pw, ph)
        else:
            sheet_w, sheet_h = min(pw, ph), max(pw, ph)

        writer = pypdf.PdfWriter()

        for page in reader.pages:
            orig_w = float(page.mediabox.width)
            orig_h = float(page.mediabox.height)

            bounds = get_page_content_bounds(page)
            if bounds:
                bx0 = max(0.0, bounds[0])
                by0 = max(0.0, bounds[1])
                bx1 = min(orig_w, bounds[2])
                by1 = min(orig_h, bounds[3])
                left_m = bx0
                right_m = orig_w - bx1
                bottom_m = by0
                top_m = orig_h - by1
                min_m = min(left_m, right_m, bottom_m, top_m)
            else:
                bx0, by0, bx1, by1 = 0.0, 0.0, orig_w, orig_h
                min_m = 0.0

            if min_m > 12.0 and (bx1 - bx0) > 20 and (by1 - by0) > 20:
                pad = 2.0
                cw = bx1 - bx0
                ch = by1 - by0
                avail_w = sheet_w - (2 * pad)
                avail_h = sheet_h - (2 * pad)

                raw_scale = min(avail_w / cw, avail_h / ch)
                scale = min(raw_scale, 1.35)

                tx = pad + (avail_w - (cw * scale)) / 2.0 - (bx0 * scale)
                ty = pad + (avail_h - (ch * scale)) / 2.0 - (by0 * scale)
            else:
                scale = min(sheet_w / orig_w, sheet_h / orig_h)
                tx = (sheet_w - (orig_w * scale)) / 2.0
                ty = (sheet_h - (orig_h * scale)) / 2.0

            new_page = writer.add_blank_page(width=sheet_w, height=sheet_h)
            op = Transformation().scale(scale, scale).translate(tx, ty)
            new_page.merge_transformed_page(page, op)

        out_path = input_pdf_path.parent / f"fp_{input_pdf_path.name}"
        with open(out_path, "wb") as f_out:
            writer.write(f_out)
        return out_path
    except Exception as opt_err:
        print(f"[AGENT FULL PAGE OPT WARNING]: {opt_err}")
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
    target_print_file = file_path

    # Convert DOC / DOCX to PDF via Word COM if available
    if ext in (".doc", ".docx"):
        try:
            import win32com.client
            word = win32com.client.Dispatch("Word.Application")
            word.Visible = False
            doc = word.Documents.Open(str(file_path.resolve()))
            pdf_path = file_path.parent / f"{file_path.stem}.pdf"
            doc.SaveAs(str(pdf_path.resolve()), FileFormat=17)
            doc.Close(False)
            word.Quit()
            if pdf_path.exists():
                target_print_file = pdf_path
                ext = ".pdf"
        except Exception as word_err:
            print("[AGENT WORD COM EXPORT WARNING]:", word_err)

    # If image with micro xerox (N-Up > 1), convert image to PDF first
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp") and pages_per_sheet > 1:
        try:
            from PIL import Image
            img = Image.open(target_print_file)
            pdf_path = target_print_file.parent / f"{target_print_file.stem}_img.pdf"
            img.convert("RGB").save(pdf_path, "PDF")
            if pdf_path.exists():
                target_print_file = pdf_path
                ext = ".pdf"
        except Exception as img_conv_err:
            print("[AGENT IMAGE CONVERT TO PDF WARNING]:", img_conv_err)

    # Process Micro Xerox layout for PDF
    if ext == ".pdf" and pages_per_sheet > 1:
        target_print_file = create_n_up_pdf(
            target_print_file,
            pages_per_sheet,
            page_order,
            paper_size=paper_size,
            orientation=orientation
        )
    elif ext == ".pdf" and pages_per_sheet <= 1 and scale_mode not in ("actual", "actual_size"):
        target_print_file = optimize_pdf_for_full_page(
            target_print_file,
            paper_size=paper_size,
            orientation=orientation
        )

    # Linux / CUPS fallback
    if sys.platform != "win32":
        lp = shutil.which("lp")
        if lp:
            cmd = [lp, "-d", printer_name, "-n", str(copies), str(target_print_file)]
            subprocess.run(cmd, check=True, timeout=15)
            return True
        return True

    # Windows PDF silent execution with SumatraPDF
    sumatra = find_sumatra_executable()
    if ext == ".pdf" and sumatra:
        settings_parts = []

        # Full Page vs Actual Size
        if scale_mode in ("actual", "actual_size"):
            settings_parts.append("noscale")
        else:
            settings_parts.append("fit")

        # Duplex (Kyocera hardware duplex support)
        if duplex in ("double", "duplex", "duplexlong", "vertical"):
            settings_parts.append("duplexlong")
        elif duplex in ("duplexshort", "short", "horizontal"):
            settings_parts.append("duplexshort")
        else:
            settings_parts.append("noduplex")

        # Orientation
        if orientation.lower() == "landscape":
            settings_parts.append("landscape")
        else:
            settings_parts.append("portrait")

        # Paper Size
        if paper_size:
            settings_parts.append(f"paper={paper_size.lower()}")

        # Copies
        settings_parts.append(f"{max(1, copies)}x")

        # Color Mode
        if color_mode.lower() in ("color", "colour"):
            settings_parts.append("color")
        else:
            settings_parts.append("monochrome")

        settings_str = ",".join(settings_parts)
        cmd = [sumatra, "-print-to", printer_name, "-print-settings", settings_str, str(target_print_file.resolve())]
        subprocess.run(cmd, check=True, timeout=30)
        return True

    # Direct Windows GDI printing for Images (JPG, PNG, BMP, WEBP)
    if ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
        try:
            import win32print
            import win32gui
            import win32ui
            from PIL import Image, ImageWin

            img = Image.open(target_print_file)
            hprinter = win32print.OpenPrinter(printer_name)
            try:
                devmode = win32print.GetPrinter(hprinter, 2)["pDevMode"]
                devmode.Orientation = 2 if orientation.lower() == "landscape" else 1
                paper_map = {"letter": 1, "legal": 5, "a4": 9}
                devmode.PaperSize = paper_map.get(paper_size.lower(), 9)
                devmode.Duplex = 2 if duplex.lower() in ("double", "duplex", "duplexlong", "vertical") else 1
                devmode.Color = 2 if color_mode.lower() in ("color", "colour") else 1
                devmode.Copies = max(1, copies)

                hdc_handle = win32gui.CreateDC("WINSPOOL", printer_name, devmode)
                hdc = win32ui.CreateDCFromHandle(hdc_handle)
            finally:
                win32print.ClosePrinter(hprinter)

            try:
                printable_width = hdc.GetDeviceCaps(8)
                printable_height = hdc.GetDeviceCaps(10)
                img_w, img_h = img.size

                if scale_mode in ("actual", "actual_size"):
                    dpi_x = hdc.GetDeviceCaps(88)
                    dpi_y = hdc.GetDeviceCaps(90)
                    img_dpi = img.info.get("dpi", (96, 96))
                    img_dpi_x = img_dpi[0] if (isinstance(img_dpi, tuple) and img_dpi[0] > 0) else 96
                    img_dpi_y = img_dpi[1] if (isinstance(img_dpi, tuple) and img_dpi[1] > 0) else 96

                    dot_w = int(img_w * (dpi_x / img_dpi_x))
                    dot_h = int(img_h * (dpi_y / img_dpi_y))
                    scale = min(1.0, printable_width / max(1, dot_w), printable_height / max(1, dot_h))
                    new_w = int(dot_w * scale)
                    new_h = int(dot_h * scale)
                else:
                    try:
                        from PIL import ImageChops
                        bg = Image.new(img.mode, img.size, img.getpixel((0, 0)))
                        diff = ImageChops.difference(img, bg)
                        bbox = diff.getbbox()
                        if bbox and (bbox[2] - bbox[0]) > 50 and (bbox[3] - bbox[1]) > 50:
                            img = img.crop(bbox)
                            img_w, img_h = img.size
                    except Exception as trim_err:
                        print("[AGENT IMAGE TRIM WARNING]:", trim_err)

                    scale = min(printable_width / img_w, printable_height / img_h)
                    new_w = int(img_w * scale)
                    new_h = int(img_h * scale)

                x = (printable_width - new_w) // 2
                y = (printable_height - new_h) // 2

                safe_doc_name = "".join(c for c in target_print_file.name if ord(c) < 128) or "document"
                for _ in range(copies):
                    hdc.StartDoc(f"PrintFlow - {safe_doc_name}")
                    hdc.StartPage()
                    dib = ImageWin.Dib(img)
                    dib.draw(hdc.GetHandleOutput(), (x, y, x + new_w, y + new_h))
                    hdc.EndPage()
                    hdc.EndDoc()
                return True
            finally:
                win32gui.DeleteDC(hdc_handle)

        except Exception as img_err:
            print("[AGENT GDI IMAGE PRINT WARNING]:", img_err)

    # Word COM direct print fallback for DOC/DOCX
    if ext in (".doc", ".docx"):
        try:
            import win32com.client
            word = win32com.client.Dispatch("Word.Application")
            word.Visible = False
            doc = word.Documents.Open(str(target_print_file.resolve()))
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
            win32api.ShellExecute(0, "printto", str(target_print_file.resolve()), f'"{printer_name}"', ".", 0)
            time.sleep(0.5)
        return True
    except Exception as win_err:
        print("[AGENT WIN32 SHELL WARNING]:", win_err)

    ps_cmd = f'Start-Process -FilePath "{str(target_print_file.resolve())}" -Verb PrintTo -ArgumentList "{printer_name}" -WindowStyle Hidden -PassThru'
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
                print_mode = job.get("print_mode", "standard")
                amount = float(job.get("amount", 2.0) or 2.0)
                file_name = job.get("file_name", "") or (Path(file_rel_path).name if file_rel_path else "document.pdf")

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
                        if claim_res.get("order"):
                            claimed_order = claim_res["order"]
                            color_mode = claimed_order.get("color_mode", color_mode)
                            copies = int(claimed_order.get("copies", copies))
                            duplex = claimed_order.get("duplex", duplex)
                            paper_size = claimed_order.get("paper_size", paper_size)
                            orientation = claimed_order.get("orientation", orientation)
                            scale_mode = claimed_order.get("scale_mode", scale_mode)
                            pages_per_sheet = int(claimed_order.get("pages_per_sheet", pages_per_sheet))
                            page_order = claimed_order.get("page_order", page_order)
                            print_mode = claimed_order.get("print_mode", print_mode)
                            amount = float(claimed_order.get("amount", amount) or amount)
                            file_name = claimed_order.get("file_name", file_name)
                except urllib.error.HTTPError as http_err:
                    if http_err.code == 409:
                        print(f"[AGENT CLAIM REJECTED] Order {order_id} already claimed by another worker.")
                        continue
                    print(f"[AGENT CLAIM ERROR] Skipping order {order_id}:", http_err)
                    continue
                except Exception as claim_err:
                    print(f"[AGENT CLAIM ERROR] Skipping order {order_id}:", claim_err)
                    continue

                print("[AGENT] Job claimed")

                target_printer = select_target_printer(color_mode, config, installed_printers)
                try:
                    local_file = download_file(backend_url, file_rel_path, agent_token, file_name)
                    print("[AGENT] Document downloaded")

                    print("[AGENT] Printer selected")

                    # Format Print Job Details Banner
                    if str(print_mode).lower() == "micro_xerox" or pages_per_sheet > 1:
                        print_type_str = "Micro Xerox"
                    elif str(color_mode).lower() in ("color", "colour"):
                        print_type_str = "Colour"
                    else:
                        print_type_str = "B&W"

                    if str(duplex).lower() in ("double", "duplex", "duplexlong", "vertical"):
                        sides_str = "Double Side"
                    else:
                        sides_str = "Single Side"

                    orientation_str = "Landscape" if str(orientation).lower() == "landscape" else "Portrait"

                    paper_map = {"a4": "A4", "letter": "Letter", "legal": "Legal"}
                    paper_size_str = paper_map.get(str(paper_size).lower(), str(paper_size).upper())

                    page_mode_str = "Actual Size" if str(scale_mode).lower() in ("actual", "actual_size") else "Full Page"

                    print("")
                    print("==================================================")
                    print("PRINTFLOW PRINT JOB")
                    print("==================================================")
                    print(f"Order ID       : {order_id}")
                    print(f"Order Value    : ₹{amount:.2f}")
                    print(f"Printer        : {target_printer}")
                    print(f"File           : {file_name}")
                    print(f"Print Type     : {print_type_str}")
                    print(f"Sides          : {sides_str}")
                    print(f"Orientation    : {orientation_str}")
                    print(f"Paper Size     : {paper_size_str}")
                    print(f"Page Mode      : {page_mode_str}")
                    print(f"Copies         : {copies}")
                    print("==================================================")
                    print("")

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
                    print("[AGENT] Print dispatched")

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
                        print("[AGENT] Print completed")

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
