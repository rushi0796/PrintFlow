import os
import sys
import json
import time
import shutil
import urllib.request
import subprocess
import re
from uuid import uuid4
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
    if not printer_names:
        raise RuntimeError("No printers installed on this system.")
    default_printer = next((p["name"] for p in installed_printers if p.get("is_default")), printer_names[0])

    is_color = color_mode.lower() in ("color", "colour")
    if is_color:
        configured_color = config.get("color_printer", "").strip()
        target = configured_color if configured_color in printer_names else next((n for n in printer_names if any(k in n.lower() for k in ("color", "epson", "l3210", "inkjet"))), "")
        if not target or target not in printer_names:
            raise RuntimeError(f"Configured Color printer '{configured_color or 'Color'}' is unavailable or offline. Job will remain queued.")
        return target
    else:
        configured_bw = config.get("bw_printer", "").strip()
        target = configured_bw if configured_bw in printer_names else next((n for n in printer_names if any(k in n.lower() for k in ("kyocera", "m2040", "3212", "b&w", "mono", "black", "laser"))), "")
        if not target or target not in printer_names:
            target = default_printer
        return target

def sanitize_filename(name: str, fallback_ext: str = ".pdf") -> str:
    raw_name = Path(name).name.strip()
    if not raw_name or raw_name.startswith("."):
        return f"doc_{uuid4().hex[:8]}{fallback_ext}"
    raw_path = Path(raw_name)
    suffix = raw_path.suffix.lower()
    if not suffix or len(suffix) > 6:
        suffix = fallback_ext
    stem = raw_path.stem
    clean_stem = "".join(c if (c.isalnum() or c in "_-") else " " for c in stem)
    import re
    clean_stem = re.sub(r"\s+", " ", clean_stem).strip()
    if not clean_stem:
        clean_stem = f"doc_{uuid4().hex[:8]}"
    return f"{clean_stem}{suffix}"

def download_file(backend_url: str, file_rel_path: str, agent_token: str = "", original_file_name: str = "") -> Path:
    clean_name = sanitize_filename(original_file_name or Path(file_rel_path).name)
    target_path = TEMP_DOWNLOAD_DIR / clean_name
    full_url = f"{backend_url.rstrip('/')}{file_rel_path if file_rel_path.startswith('/') else '/' + file_rel_path}"

    req = urllib.request.Request(full_url, headers={"User-Agent": "PrintFlowAgent/1.0", "X-Print-Agent-Token": agent_token})
    try:
        with urllib.request.urlopen(req, timeout=30) as response, target_path.open("wb") as out_file:
            shutil.copyfileobj(response, out_file)
    except Exception:
        if target_path.exists():
            try:
                target_path.unlink()
            except Exception:
                pass
        raise

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
                        llx = float(src_page.mediabox.lower_left[0])
                        lly = float(src_page.mediabox.lower_left[1])

                        scale = min(cell_w / orig_w, cell_h / orig_h) * 0.96 if (orig_w > 0 and orig_h > 0) else 1.0
                        scaled_w = orig_w * scale
                        scaled_h = orig_h * scale

                        tx = c * cell_w + (cell_w - scaled_w) / 2.0
                        ty = sheet_h - ((r + 1) * cell_h) + (cell_h - scaled_h) / 2.0

                        op = Transformation().translate(-llx, -lly).scale(scale, scale).translate(tx, ty)
                        blank_page.merge_transformed_page(src_page, op)
            i += pages_per_sheet

        output_path = input_pdf_path.parent / f"nup_{pages_per_sheet}_{input_pdf_path.name}"
        with open(output_path, "wb") as f_out:
            writer.write(f_out)
        return output_path
    except Exception as nup_err:
        print(f"[MICRO XEROX N-UP WARNING]: {nup_err}")
        return input_pdf_path

def extract_pdf_page_subset(input_pdf_path: Path, page_range_str: str) -> Path:
    if not page_range_str or str(page_range_str).strip().lower() == "all":
        return input_pdf_path
    try:
        import pypdf
        reader = pypdf.PdfReader(str(input_pdf_path))
        total_pages = len(reader.pages)
        if total_pages <= 0:
            return input_pdf_path

        selected_pages = []
        cleaned = str(page_range_str).strip().lower()
        if cleaned == "even":
            selected_pages = [p for p in range(2, total_pages + 1, 2)]
        elif cleaned == "odd":
            selected_pages = [p for p in range(1, total_pages + 1, 2)]
        else:
            for part in cleaned.split(","):
                part = part.strip()
                if not part:
                    continue
                if "-" in part:
                    subparts = part.split("-")
                    if len(subparts) == 2 and subparts[0].strip().isdigit() and subparts[1].strip().isdigit():
                        start_p = int(subparts[0].strip())
                        end_p = int(subparts[1].strip())
                        if start_p <= end_p:
                            for p in range(start_p, end_p + 1):
                                if 1 <= p <= total_pages and p not in selected_pages:
                                    selected_pages.append(p)
                elif part.isdigit():
                    p = int(part)
                    if 1 <= p <= total_pages and p not in selected_pages:
                        selected_pages.append(p)

        if not selected_pages:
            print(f"[PAGE SUBSET WARNING] Page range '{page_range_str}' resolved to 0 valid pages for document with {total_pages} page(s). Printing all pages as fallback.")
            return input_pdf_path

        selected_pages.sort()
        writer = pypdf.PdfWriter()
        for p_num in selected_pages:
            writer.add_page(reader.pages[p_num - 1])

        out_path = input_pdf_path.parent / f"subset_{input_pdf_path.name}"
        with open(out_path, "wb") as f_out:
            writer.write(f_out)
        print(f"[AGENT PAGE FILTER] Extracted {len(selected_pages)} page(s) ({selected_pages}) from {total_pages} total page(s).")
        return out_path
    except Exception as exc:
        print(f"[PAGE SUBSET ERROR]: {exc}")
        return input_pdf_path

def optimize_pdf_for_full_page(
    input_pdf_path: Path,
    paper_size: str = "a4",
    orientation: str = "portrait"
) -> Path:
    """
    Scales the ENTIRE original page/image canvas proportionally corner-to-corner to cover
    and fill the selected paper dimensions to maximum usable printable area without distortion.
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
            llx = float(page.mediabox.lower_left[0])
            lly = float(page.mediabox.lower_left[1])

            # Proportional scale factor to maximum usable printable area without distortion
            if orig_w <= 0 or orig_h <= 0:
                scale = 1.0
            else:
                scale = min(sheet_w / orig_w, sheet_h / orig_h)

            scaled_w = orig_w * scale
            scaled_h = orig_h * scale
            offset_x = (sheet_w - scaled_w) / 2.0
            offset_y = (sheet_h - scaled_h) / 2.0

            new_page = writer.add_blank_page(width=sheet_w, height=sheet_h)
            op = Transformation().translate(-llx, -lly).scale(scale, scale).translate(offset_x, offset_y)
            new_page.merge_transformed_page(page, op)

        out_path = input_pdf_path.parent / f"fp_{input_pdf_path.name}"
        with open(out_path, "wb") as f_out:
            writer.write(f_out)
        return out_path
    except Exception as opt_err:
        print(f"[FULL PAGE SCALE WARNING]: {opt_err}")
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
    page_order: str = "horizontal",
    page_range: str = "all"
):
    ext = file_path.suffix.lower()
    target_print_file = file_path
    is_image = ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp")

    raw_color = str(color_mode).lower()
    is_color = raw_color in ("color", "colour")
    if is_color:
        duplex = "single"
        color_mode = "color"
    else:
        color_mode = "black_white"

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

    # Universal Image-to-PDF Conversion for Rock-Solid Printing (Single page & Micro Xerox)
    if is_image:
        try:
            from PIL import Image
            img = Image.open(target_print_file)
            # Handle transparency (RGBA, LA, or P with transparency)
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                bg.paste(img, mask=img.split()[3])
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")
            clean_stem = re.sub(r'[^a-zA-Z0-9_\-]+', '_', target_print_file.stem).strip('_') or 'image'
            pdf_path = target_print_file.parent / f"{clean_stem}_img.pdf"
            img.save(pdf_path, "PDF", resolution=300.0)
            if pdf_path.exists():
                target_print_file = pdf_path
                ext = ".pdf"
        except Exception as img_conv_err:
            print("[AGENT IMAGE CONVERT TO PDF WARNING]:", img_conv_err)

    # Filter PDF to requested page subset (All, Custom e.g. 1,3,5-8,12, Even, Odd)
    if ext == ".pdf" and page_range and str(page_range).strip().lower() != "all":
        target_print_file = extract_pdf_page_subset(target_print_file, page_range)

    # Process Micro Xerox layout for PDF
    if ext == ".pdf" and pages_per_sheet > 1:
        target_print_file = create_n_up_pdf(
            target_print_file,
            pages_per_sheet,
            page_order,
            paper_size=paper_size,
            orientation=orientation
        )
    elif ext == ".pdf" and pages_per_sheet <= 1 and (is_image or scale_mode not in ("actual", "actual_size")):
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

        # Full Page vs Actual Size:
        # For Full Page, SumatraPDF 'fit' utilizes the maximum physical printable area supported by the printer.
        if scale_mode in ("actual", "actual_size") and not is_image:
            settings_parts.append("shrink")
        else:
            settings_parts.append("fit")

        # Duplex (Kyocera hardware duplex support)
        if is_color or duplex == "single":
            settings_parts.append("noduplex")
        elif duplex in ("duplex_short", "duplexshort", "short_edge", "short", "horizontal"):
            settings_parts.append("duplexshort")
        elif duplex in ("duplex_long", "duplexlong", "long_edge", "double", "duplex", "vertical"):
            settings_parts.append("duplexlong")
        else:
            settings_parts.append("noduplex")

        # Orientation
        if orientation.lower() == "landscape":
            settings_parts.append("landscape")
        else:
            settings_parts.append("portrait")

        # Paper Size & Paper Kind (DMPAPER_A4 = 9, DMPAPER_LETTER = 1, DMPAPER_LEGAL = 5)
        paper_map = {"a4": (9, "a4"), "letter": (1, "letter"), "legal": (5, "legal")}
        pid, pname = paper_map.get(paper_size.lower(), (9, "a4"))
        settings_parts.append(f"paper={pname}")
        settings_parts.append(f"paperkind={pid}")

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
            if img.mode != "RGB":
                img = img.convert("RGB")
            hprinter = win32print.OpenPrinter(printer_name)
            try:
                devmode = win32print.GetPrinter(hprinter, 2)["pDevMode"]
                devmode.Orientation = 2 if orientation.lower() == "landscape" else 1
                paper_map = {"letter": 1, "legal": 5, "a4": 9}
                devmode.PaperSize = paper_map.get(paper_size.lower(), 9)
                devmode.Duplex = 1 if is_color else (3 if duplex.lower() in ("duplex_short", "duplexshort", "short_edge", "short", "horizontal") else (2 if duplex.lower() in ("duplex_long", "duplexlong", "long_edge", "double", "duplex", "vertical") else 1))
                devmode.Color = 2 if is_color else 1
                devmode.Copies = max(1, copies)

                hdc_handle = win32gui.CreateDC("WINSPOOL", printer_name, devmode)
                hdc = win32ui.CreateDCFromHandle(hdc_handle)
            finally:
                win32print.ClosePrinter(hprinter)

            try:
                printable_width = hdc.GetDeviceCaps(8)
                printable_height = hdc.GetDeviceCaps(10)
                img_w, img_h = img.size

                if scale_mode in ("actual", "actual_size") and not is_image:
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
                    new_w = printable_width
                    new_h = printable_height
                    x = 0
                    y = 0

                safe_doc_name = "".join(c for c in target_print_file.name if ord(c) < 128 and c.isalnum()) or "document"
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

    # Windows Shell fallback for formats with PrintTo support (PDF/Word/etc. - NOT images)
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
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

    # Image fallback when Sumatra and GDI are unavailable: mspaint silent print
    try:
        mspaint = shutil.which("mspaint.exe") or "mspaint"
        cmd = [mspaint, "/pt", str(target_print_file.resolve()), printer_name]
        subprocess.run(cmd, check=True, timeout=15)
        return True
    except Exception as ms_err:
        print("[AGENT MSPAINT PRINT WARNING]:", ms_err)
        raise RuntimeError(f"Could not print image file {target_print_file.name} to {printer_name}")

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
    print(" Agent Status   : DISCOVERING PRINTERS...")

    installed_printers = get_installed_windows_printers()
    printer_summary = [p["name"] for p in installed_printers if "OneNote" not in p["name"] and "Fax" not in p["name"] and "XPS" not in p["name"]]
    print(f" Detected {len(installed_printers)} printer(s): {', '.join(printer_summary)}")
    print(" Agent Status   : READY & POLLING FOR JOBS...\n")

    loop_count = 0
    while True:
        try:
            loop_count += 1
            if loop_count % 20 == 0:
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
                page_range = job.get("page_range", "all") or "all"
                amount = float(job.get("amount", 2.0) or 2.0)
                file_name = job.get("file_name", "") or (Path(file_rel_path).name if file_rel_path else "document.pdf")
                is_color = str(color_mode).lower() in ("color", "colour")

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
                            raw_color = str(claimed_order.get("color_mode", color_mode)).lower()
                            is_color = raw_color in ("color", "colour")
                            color_mode = "color" if is_color else "black_white"
                            if is_color:
                                duplex = "single"
                                binding = ""
                            else:
                                duplex = str(claimed_order.get("duplex", duplex)).lower()
                                binding = str(claimed_order.get("binding", "")).lower()
                                if duplex in ("double", "duplex"):
                                    duplex = "duplex_short" if binding == "short_edge" else "duplex_long"

                            copies = int(claimed_order.get("copies", copies))
                            paper_size = claimed_order.get("paper_size", paper_size)
                            orientation = claimed_order.get("orientation", orientation)
                            scale_mode = claimed_order.get("scale_mode", scale_mode)
                            print_mode = claimed_order.get("print_mode", print_mode)
                            pages_per_sheet = int(claimed_order.get("pages_per_sheet", pages_per_sheet))
                            if str(print_mode).lower() != "micro_xerox":
                                pages_per_sheet = 1
                            page_order = claimed_order.get("page_order", page_order)
                            page_range = claimed_order.get("page_range", page_range) or "all"
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

                target_printer = select_target_printer(color_mode, config, installed_printers)
                print(f"[AGENT CLAIMED] {order_id}, {target_printer}")
                try:
                    # Format Print Job Details Banner
                    if str(print_mode).lower() == "micro_xerox" and pages_per_sheet > 1:
                        print_type_str = f"Micro Xerox ({pages_per_sheet}-Up)"
                    else:
                        print_type_str = "Standard"

                    color_mode_str = "Colour" if is_color else "B&W"

                    if is_color or duplex == "single":
                        sides_str = "Single Side"
                    elif duplex in ("duplex_short", "duplexshort", "short_edge", "short"):
                        sides_str = "Double Side (Short Edge)"
                    elif duplex in ("duplex_long", "duplexlong", "long_edge", "double", "duplex", "vertical"):
                        sides_str = "Double Side (Long Edge)"
                    else:
                        sides_str = "Single Side"

                    orientation_str = "Landscape" if str(orientation).lower() == "landscape" else "Portrait"

                    paper_map = {"a4": "A4", "letter": "Letter", "legal": "Legal"}
                    paper_size_str = paper_map.get(str(paper_size).lower(), str(paper_size).upper())

                    is_img_job = Path(file_name).suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".bmp")
                    page_mode_str = "Full Page" if is_img_job else ("Actual Size" if str(scale_mode).lower() in ("actual", "actual_size") else "Full Page")

                    print("")
                    print("==================================================")
                    print("PRINTFLOW PRINT JOB")
                    print("==================================================")
                    print(f"Order ID       : {order_id}")
                    print(f"Order Value    : ₹{amount:.2f}")
                    print(f"Printer        : {target_printer}")
                    print(f"File           : {file_name}")
                    print(f"Pages          : {page_range}")
                    print(f"Print Type     : {print_type_str}")
                    print(f"Color Mode     : {color_mode_str}")
                    print(f"Sides          : {sides_str}")
                    print(f"Paper Size     : {paper_size_str}")
                    print(f"Orientation    : {orientation_str}")
                    print(f"Page Mode      : {page_mode_str}")
                    print(f"Copies         : {copies}")
                    print("==================================================")
                    print("")

                    print("[AGENT] Job claimed")
                    local_file = download_file(backend_url, file_rel_path, agent_token, file_name)
                    print("[AGENT] Document downloaded")
                    print("[AGENT] Printer selected")

                    print(f"[PRINTING] {order_id}, {file_name}")
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
                        page_order=page_order,
                        page_range=page_range
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
                        print(f"[PRINT COMPLETED] {order_id}")
                        print("[AGENT] Print completed")

                    time.sleep(2.5)
                    try:
                        clean_stem = local_file.stem.strip()
                        for tmp_f in TEMP_DOWNLOAD_DIR.glob("*"):
                            if tmp_f.is_file() and (tmp_f.name == local_file.name or (clean_stem and clean_stem in tmp_f.name)):
                                try:
                                    tmp_f.unlink()
                                    print(f"[AGENT LOCAL PRIVACY CLEANUP] Local temp file '{tmp_f.name}' deleted 2.5s after printing.")
                                except Exception:
                                    pass
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
