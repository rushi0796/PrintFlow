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
        enum_list = []
        try:
            import win32print
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            enum_list = win32print.EnumPrinters(flags)
        except Exception as e:
            print("[AGENT WIN32PRINT ENUM WARNING]:", e)

        ps_info = {}
        try:
            ps_cmd = 'Get-Printer | Select-Object Name, DriverName, PrinterStatus, IsDefault | ConvertTo-Json'
            res = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, timeout=10)
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                if isinstance(data, dict):
                    data = [data]
                for p in data:
                    pname = p.get("Name", "")
                    if pname:
                        ps_info[pname] = p
        except Exception as e:
            print("[AGENT POWERSHELL PRINTER WARNING]:", e)

        # Iterate over discovered printers
        printer_names = [p[2] for p in enum_list] if enum_list else list(ps_info.keys())
        for name in printer_names:
            p_ps = ps_info.get(name, {})
            driver_name = p_ps.get("DriverName", "")
            is_default = bool(p_ps.get("IsDefault", False))

            duplex_sup = False
            color_sup = False
            paper_sizes = []
            is_online = True
            status_str = "Normal"

            try:
                import win32print
                d_val = win32print.DeviceCapabilities(name, "", 7)  # DC_DUPLEX
                duplex_sup = bool(d_val == 1)
            except Exception:
                pass

            try:
                import win32print
                c_val = win32print.DeviceCapabilities(name, "", 32)  # DC_COLORDEVICE
                color_sup = bool(c_val == 1)
            except Exception:
                pass

            try:
                import win32print
                p_vals = win32print.DeviceCapabilities(name, "", 2)   # DC_PAPERS
                paper_map = {1: "Letter", 5: "Legal", 9: "A4"}
                for code, pname in paper_map.items():
                    if code in p_vals:
                        paper_sizes.append(pname)
            except Exception:
                pass

            try:
                import win32print
                h = win32print.OpenPrinter(name)
                try:
                    info = win32print.GetPrinter(h, 2)
                    attr = info.get("Attributes", 0)
                    st = info.get("Status", 0)
                    if bool(attr & 0x00000400) or bool(st & 0x00000080):
                        is_online = False
                        status_str = "Offline"
                finally:
                    win32print.ClosePrinter(h)
            except Exception:
                pass

            if not paper_sizes:
                paper_sizes = ["A4", "Letter"]

            printers.append({
                "name": name,
                "driver": driver_name,
                "status": status_str,
                "is_default": is_default,
                "duplex_supported": duplex_sup,
                "color_supported": color_sup,
                "paper_sizes": paper_sizes,
                "online": is_online
            })

    if not printers:
        printers.append({
            "name": "Microsoft Print to PDF",
            "driver": "Virtual",
            "status": "Normal",
            "is_default": True,
            "duplex_supported": False,
            "color_supported": True,
            "paper_sizes": ["A4", "Letter", "Legal"],
            "online": True
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
        # 1. Check if configured color printer is present and online
        if configured_color and configured_color in printer_names:
            p_obj = next((p for p in installed_printers if p["name"] == configured_color), None)
            if p_obj and p_obj.get("online", True):
                return configured_color
        # 2. Look for any online color-capable printer (color_supported == True or matches color/epson/inkjet)
        online_color = [
            p["name"] for p in installed_printers
            if p.get("online", True) and (p.get("color_supported") is True or any(k in p["name"].lower() for k in ("color", "epson", "inkjet", "l3210", "l3110")))
        ]
        if online_color:
            # Prefer L3210 or explicitly named color
            pref = next((n for n in online_color if "l3210" in n.lower()), online_color[0])
            return pref
        # 3. Fallback to configured color even if reported offline (spooler will queue)
        if configured_color and configured_color in printer_names:
            return configured_color
        # 4. Fallback to any color printer by name
        fallback_color = next((n for n in printer_names if any(k in n.lower() for k in ("color", "epson", "l3210", "l3110", "inkjet"))), "")
        if fallback_color:
            return fallback_color
        raise RuntimeError(f"Configured Color printer '{configured_color or 'Color'}' is unavailable or offline. Job will remain queued.")
    else:
        configured_bw = config.get("bw_printer", "").strip()
        # 1. Check if configured B&W printer is present and online
        if configured_bw and configured_bw in printer_names:
            p_obj = next((p for p in installed_printers if p["name"] == configured_bw), None)
            if p_obj and p_obj.get("online", True):
                return configured_bw
        # 2. Look for any online B&W / laser printer
        online_bw = [
            p["name"] for p in installed_printers
            if p.get("online", True) and any(k in p["name"].lower() for k in ("kyocera", "m2040", "3212", "b&w", "mono", "black", "laser"))
        ]
        if online_bw:
            return online_bw[0]
        if configured_bw and configured_bw in printer_names:
            return configured_bw
        target = next((n for n in printer_names if any(k in n.lower() for k in ("kyocera", "m2040", "3212", "b&w", "mono", "black", "laser"))), "")
        if not target:
            target = default_printer
        return target

def get_printer_hardware_caps(printer_name: str = "", orientation: str = "portrait", paper_size: str = "a4") -> dict:
    """
    Queries the REAL Windows printer device context / driver for:
    - PHYSICALWIDTH, PHYSICALHEIGHT, HORZRES, VERTRES
    - PHYSICALOFFSETX, PHYSICALOFFSETY, LOGPIXELSX, LOGPIXELSY
    Calculates exact printable rectangle and hard hardware non-printable margins.
    """
    is_landscape = (str(orientation).lower() == "landscape")
    paper_map = {"a4": 9, "letter": 1, "legal": 5}
    paper_kind = paper_map.get(str(paper_size).lower(), 9)

    paper_dots_map = {
        "a4": (4961, 7016),
        "letter": (5100, 6600),
        "legal": (5100, 8400)
    }
    pw_dots, ph_dots = paper_dots_map.get(str(paper_size).lower(), (4961, 7016))
    if is_landscape:
        pw_dots, ph_dots = ph_dots, pw_dots

    margin_dots = 99
    res = {
        "HORZRES": pw_dots - (margin_dots * 2),
        "VERTRES": ph_dots - (margin_dots * 2),
        "LOGPIXELSX": 600,
        "LOGPIXELSY": 600,
        "PHYSICALWIDTH": pw_dots,
        "PHYSICALHEIGHT": ph_dots,
        "PHYSICALOFFSETX": margin_dots,
        "PHYSICALOFFSETY": margin_dots,
    }

    if sys.platform == "win32" and printer_name:
        try:
            import win32print, win32gui, win32ui, win32con
            hprinter = win32print.OpenPrinter(printer_name)
            try:
                pinfo = win32print.GetPrinter(hprinter, 2)
                devmode = pinfo["pDevMode"]
                devmode.PaperSize = paper_kind
                devmode.Orientation = 2 if is_landscape else 1
                devmode.Fields |= win32con.DM_PAPERSIZE | win32con.DM_ORIENTATION

                hdc_handle = win32gui.CreateDC("WINSPOOL", printer_name, devmode)
                try:
                    hdc = win32ui.CreateDCFromHandle(hdc_handle)
                    res["HORZRES"] = hdc.GetDeviceCaps(8)
                    res["VERTRES"] = hdc.GetDeviceCaps(10)
                    res["LOGPIXELSX"] = hdc.GetDeviceCaps(88)
                    res["LOGPIXELSY"] = hdc.GetDeviceCaps(90)
                    res["PHYSICALWIDTH"] = hdc.GetDeviceCaps(110)
                    res["PHYSICALHEIGHT"] = hdc.GetDeviceCaps(111)
                    res["PHYSICALOFFSETX"] = hdc.GetDeviceCaps(112)
                    res["PHYSICALOFFSETY"] = hdc.GetDeviceCaps(113)
                finally:
                    win32gui.DeleteDC(hdc_handle)
            finally:
                win32print.ClosePrinter(hprinter)
        except Exception as cap_err:
            print(f"[PRINTER DEVICE CAPS WARNING]: {cap_err}")

    dpi_x = float(res["LOGPIXELSX"] or 600)
    dpi_y = float(res["LOGPIXELSY"] or 600)

    res["paper_w_mm"] = res["PHYSICALWIDTH"] / dpi_x * 25.4
    res["paper_h_mm"] = res["PHYSICALHEIGHT"] / dpi_y * 25.4
    res["paper_w_pt"] = res["PHYSICALWIDTH"] / dpi_x * 72.0
    res["paper_h_pt"] = res["PHYSICALHEIGHT"] / dpi_y * 72.0

    res["printable_w_mm"] = res["HORZRES"] / dpi_x * 25.4
    res["printable_h_mm"] = res["VERTRES"] / dpi_y * 25.4
    res["printable_w_pt"] = res["HORZRES"] / dpi_x * 72.0
    res["printable_h_pt"] = res["VERTRES"] / dpi_y * 72.0

    res["left_margin_dots"] = res["PHYSICALOFFSETX"]
    res["left_margin_mm"] = res["left_margin_dots"] / dpi_x * 25.4
    res["left_margin_pt"] = res["left_margin_dots"] / dpi_x * 72.0

    res["right_margin_dots"] = res["PHYSICALWIDTH"] - (res["PHYSICALOFFSETX"] + res["HORZRES"])
    res["right_margin_mm"] = res["right_margin_dots"] / dpi_x * 25.4
    res["right_margin_pt"] = res["right_margin_dots"] / dpi_x * 72.0

    res["top_margin_dots"] = res["PHYSICALOFFSETY"]
    res["top_margin_mm"] = res["top_margin_dots"] / dpi_y * 25.4
    res["top_margin_pt"] = res["top_margin_dots"] / dpi_y * 72.0

    res["bottom_margin_dots"] = res["PHYSICALHEIGHT"] - (res["PHYSICALOFFSETY"] + res["VERTRES"])
    res["bottom_margin_mm"] = res["bottom_margin_dots"] / dpi_y * 25.4
    res["bottom_margin_pt"] = res["bottom_margin_dots"] / dpi_y * 72.0

    return res

def log_printer_margins(caps: dict):
    print(f"[PHYSICAL PAPER SIZE] {caps['paper_w_mm']:.1f}mm x {caps['paper_h_mm']:.1f}mm ({caps['paper_w_pt']:.1f}pt x {caps['paper_h_pt']:.1f}pt)")
    print(f"[PRINTABLE AREA] {caps['printable_w_mm']:.1f}mm x {caps['printable_h_mm']:.1f}mm ({caps['printable_w_pt']:.1f}pt x {caps['printable_h_pt']:.1f}pt)")
    print(f"[LEFT HARD MARGIN] {caps['left_margin_mm']:.1f}mm ({caps['left_margin_pt']:.1f}pt)")
    print(f"[RIGHT HARD MARGIN] {caps['right_margin_mm']:.1f}mm ({caps['right_margin_pt']:.1f}pt)")
    print(f"[TOP HARD MARGIN] {caps['top_margin_mm']:.1f}mm ({caps['top_margin_pt']:.1f}pt)")
    print(f"[BOTTOM HARD MARGIN] {caps['bottom_margin_mm']:.1f}mm ({caps['bottom_margin_pt']:.1f}pt)")
    print("[HARDWARE NON-PRINTABLE MARGIN] Unavoidable physical printer mechanism margin (Kyocera ECOSYS laser engine does not support A4 borderless)")
    print("[SOFTWARE MARGIN] 0.0mm (0.0pt) - Zero artificial PrintFlow margins added")


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

    # Fast-path: Check if file exists locally in uploads directory
    rel_clean = str(file_rel_path).replace("\\", "/").lstrip("/")
    local_candidates = [
        BASE_DIR / rel_clean,
        BASE_DIR / "uploads" / Path(file_rel_path).name,
        Path(file_rel_path)
    ]
    for cand in local_candidates:
        if cand.is_file() and cand.stat().st_size > 0:
            shutil.copyfile(cand, target_path)
            return target_path

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
    orientation: str = "portrait",
    printer_name: str = ""
) -> Path:
    pages_per_sheet = int(pages_per_sheet)
    if pages_per_sheet <= 1:
        return input_pdf_path

    if not input_pdf_path.exists():
        raise RuntimeError(f"MICRO_NUP_INPUT_NOT_FOUND: '{input_pdf_path}' does not exist")

    import pypdf
    from pypdf import Transformation
    import math

    reader = pypdf.PdfReader(str(input_pdf_path))
    num_pages = len(reader.pages)
    if num_pages == 0:
        raise RuntimeError(f"MICRO_NUP_EMPTY_INPUT: Input PDF '{input_pdf_path.name}' has 0 pages")

    caps = get_printer_hardware_caps(printer_name, orientation, paper_size)
    sheet_w = caps["paper_w_pt"]
    sheet_h = caps["paper_h_pt"]
    printable_w = caps["printable_w_pt"]
    printable_h = caps["printable_h_pt"]
    left_margin_pt = caps["left_margin_pt"]
    top_margin_pt = caps["top_margin_pt"]

    is_landscape = (str(orientation).lower() == "landscape")
    grid_map = {
        2: (2, 1) if is_landscape else (1, 2),
        4: (2, 2),
        6: (3, 2) if is_landscape else (2, 3),
        9: (3, 3),
        16: (4, 4),
    }
    cols, rows = grid_map.get(pages_per_sheet, (2, 1) if is_landscape else (1, 2))

    cell_w = printable_w / cols
    cell_h = printable_h / rows

    writer = pypdf.PdfWriter()
    expected_sheets = math.ceil(num_pages / pages_per_sheet)

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

                    if orig_w > 0 and orig_h > 0:
                        # Strictly proportional scaling to fit inside the cell - ZERO arbitrary reduction
                        scale = min(cell_w / orig_w, cell_h / orig_h)
                        scaled_w = orig_w * scale
                        scaled_h = orig_h * scale

                        x_cell_left = left_margin_pt + c * cell_w
                        y_cell_top = (sheet_h - top_margin_pt) - r * cell_h
                        y_cell_bottom = y_cell_top - cell_h

                        tx = x_cell_left + (cell_w - scaled_w) / 2.0
                        ty = y_cell_bottom + (cell_h - scaled_h) / 2.0

                        op = Transformation().translate(-llx, -lly).scale(scale, scale).translate(tx, ty)
                        blank_page.merge_transformed_page(src_page, op)
        i += pages_per_sheet

    output_path = input_pdf_path.parent / f"nup_{pages_per_sheet}_{input_pdf_path.name}"
    with open(output_path, "wb") as f_out:
        writer.write(f_out)

    # HARD PRE-PRINT ASSERTIONS ON OUTPUT N-UP PDF
    verify_reader = pypdf.PdfReader(str(output_path))
    actual_sheets = len(verify_reader.pages)
    if actual_sheets != expected_sheets:
        raise RuntimeError(
            f"MICRO_OUTPUT_PAGE_COUNT_MISMATCH: Expected {expected_sheets} sheet(s) for {num_pages} source pages "
            f"in {pages_per_sheet}-Up ({orientation}), but generated {actual_sheets} sheet(s)!"
        )

    for p_idx, page in enumerate(verify_reader.pages):
        pw = float(page.mediabox.width)
        ph = float(page.mediabox.height)
        if abs(pw - sheet_w) > 2.0 or abs(ph - sheet_h) > 2.0:
            raise RuntimeError(
                f"MICRO_SHEET_DIMENSION_MISMATCH: Sheet {p_idx+1} dimension {pw:.1f}x{ph:.1f} pt "
                f"does not match expected paper dimensions {sheet_w:.1f}x{sheet_h:.1f} pt!"
            )

    print("")
    print(f"[MICRO] source_pages={num_pages}")
    print(f"[MICRO] n_up={pages_per_sheet}")
    print(f"[MICRO] expected_sheets={expected_sheets}")
    print(f"[MICRO] generated_sheets={actual_sheets}")
    print(f"[MICRO] page_order={page_order.lower()}")
    print(f"[MICRO] print_ready_pdf={output_path.resolve()}")
    for s in range(1, expected_sheets + 1):
        s_start = (s - 1) * pages_per_sheet + 1
        s_end = min(s * pages_per_sheet, num_pages)
        print(f"[MICRO] sheet={s} source_pages={s_start}-{s_end}")
    print("")

    print(f"[MICRO XEROX N-UP ENGINE] Synthesized {actual_sheets} sheet(s) for {num_pages} source pages ({pages_per_sheet}-Up, {orientation}, {cols}x{rows} grid).")
    return output_path

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
    orientation: str = "portrait",
    scale_mode: str = "fit",
    printer_name: str = ""
) -> Path:
    """
    Scales content proportionally to fill 100% of the REAL printer printable rectangle:
    - Queries hardware printable bounds from the printer DC.
    - Zero software margin (0.0mm).
    - Preserves aspect ratio with zero distortion or stretching.
    - Centers content using the printer's actual physical offsets.
    - Preserves unavoidable hardware non-printable borders without adding artificial margins.
    - NO SILENT FALLBACK: Hard raises on failure.
    """
    try:
        import pypdf
        from pypdf import Transformation

        reader = pypdf.PdfReader(str(input_pdf_path))
        num_pages = len(reader.pages)
        if num_pages == 0:
            raise RuntimeError(f"FULL_PAGE_EMPTY_INPUT: Input PDF '{input_pdf_path.name}' has 0 pages")

        target_orient = str(orientation).strip().lower()
        writer = pypdf.PdfWriter()

        for page in reader.pages:
            orig_w = float(page.mediabox.width)
            orig_h = float(page.mediabox.height)

            if target_orient == "landscape":
                page_is_landscape = True
                if orig_w < orig_h:
                    page.rotate(90)
                    page.transfer_rotation_to_content()
                    orig_w, orig_h = orig_h, orig_w
            elif target_orient == "portrait":
                page_is_landscape = False
                if orig_w > orig_h:
                    page.rotate(90)
                    page.transfer_rotation_to_content()
                    orig_w, orig_h = orig_h, orig_w
            else:
                page_is_landscape = (orig_w >= orig_h)

            page_caps = get_printer_hardware_caps(printer_name, "landscape" if page_is_landscape else "portrait", paper_size)
            p_sheet_w = page_caps["paper_w_pt"]
            p_sheet_h = page_caps["paper_h_pt"]
            p_printable_w = page_caps["printable_w_pt"]
            p_printable_h = page_caps["printable_h_pt"]
            p_left_m = page_caps["left_margin_pt"]
            p_bottom_m = page_caps["bottom_margin_pt"]

            llx = float(page.mediabox.lower_left[0])
            lly = float(page.mediabox.lower_left[1])

            if orig_w <= 0 or orig_h <= 0:
                scale = 1.0
            elif scale_mode in ("actual", "actual_size"):
                scale = min(1.0, p_printable_w / orig_w, p_printable_h / orig_h)
            else:
                scale = min(p_printable_w / orig_w, p_printable_h / orig_h)

            scaled_w = orig_w * scale
            scaled_h = orig_h * scale
            offset_x = p_left_m + (p_printable_w - scaled_w) / 2.0
            offset_y = p_bottom_m + (p_printable_h - scaled_h) / 2.0

            new_page = writer.add_blank_page(width=p_sheet_w, height=p_sheet_h)
            op = Transformation().translate(-llx, -lly).scale(scale, scale).translate(offset_x, offset_y)
            new_page.merge_transformed_page(page, op)

        out_path = input_pdf_path.parent / f"fp_{input_pdf_path.name}"
        with open(out_path, "wb") as f_out:
            writer.write(f_out)
        return out_path
    except Exception as opt_err:
        print(f"[FULL PAGE SCALE ERROR]: {opt_err}")
        raise RuntimeError(f"FULL_PAGE_OPTIMIZATION_FAILED: {opt_err}") from opt_err

def update_order_agent_status(
    backend_url: str,
    agent_token: str,
    order_id: str,
    status: str,
    spooler_job_id: int = 0,
    error: str = "",
    printed_by_printer: str = ""
):
    url = f"{backend_url}/api/agent/complete/{order_id}"
    payload = {
        "status": status,
        "spooler_job_id": spooler_job_id,
        "printed_by_printer": printed_by_printer
    }
    if error:
        payload["error"] = error
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Print-Agent-Token": agent_token,
            "User-Agent": "PrintFlowAgent/1.0"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[AGENT STATUS UPDATE ERROR] Failed to send status '{status}' for order '{order_id}':", e)
        return None

def monitor_spooler_job(backend_url: str, agent_token: str, order_id: str, printer_name: str, spooler_job_id: int):
    print(f"[SPOOLER MONITOR] Monitoring Job #{spooler_job_id} on '{printer_name}'...")
    if sys.platform != "win32":
        update_order_agent_status(backend_url, agent_token, order_id, "COMPLETED", spooler_job_id, printed_by_printer=printer_name)
        return

    start_t = time.time()
    max_wait = 180.0
    seen_printing = False

    while (time.time() - start_t) < max_wait:
        try:
            import win32print
            h = win32print.OpenPrinter(printer_name)
            try:
                jobs = win32print.EnumJobs(h, 0, 999, 2)
            finally:
                win32print.ClosePrinter(h)

            matching = next((j for j in jobs if j.get("JobId") == spooler_job_id), None)
            if not matching:
                print(f"[SPOOLER MONITOR] Job #{spooler_job_id} cleared from spooler. Marking COMPLETED.")
                update_order_agent_status(backend_url, agent_token, order_id, "COMPLETED", spooler_job_id, printed_by_printer=printer_name)
                return

            st = matching.get("Status", 0)
            if bool(st & 0x00000002) or bool(st & 0x00000200):  # ERROR or BLOCKED_DEVQ
                err_msg = f"Printer spooler reported error for Job #{spooler_job_id} on '{printer_name}'"
                print(f"[SPOOLER MONITOR ERROR] {err_msg}")
                update_order_agent_status(backend_url, agent_token, order_id, "FAILED", spooler_job_id, error=err_msg, printed_by_printer=printer_name)
                return

            if (bool(st & 0x00000010) or bool(st & 0x00000001)) and not seen_printing:  # PRINTING or PAUSED
                seen_printing = True
                print(f"[SPOOLER MONITOR] Job #{spooler_job_id} is actively printing in Windows spooler.")
                update_order_agent_status(backend_url, agent_token, order_id, "PRINTING", spooler_job_id, printed_by_printer=printer_name)

            time.sleep(1.0)
        except Exception as mon_err:
            print(f"[SPOOLER MONITOR WARNING] {mon_err}")
            break

    update_order_agent_status(backend_url, agent_token, order_id, "COMPLETED", spooler_job_id, printed_by_printer=printer_name)

def convert_image_to_pdf_page(
    image_path: Path,
    out_pdf_path: Path,
    orientation: str = "portrait",
    paper_size: str = "a4",
    scale_mode: str = "fit",
    printer_name: str = ""
) -> Path:
    from PIL import Image
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader

    paper_map = {
        "a4": (595.276, 841.890),
        "letter": (612.0, 792.0),
        "legal": (612.0, 1008.0)
    }
    std_w, std_h = paper_map.get(paper_size.lower(), (595.276, 841.890))
    is_landscape = (str(orientation).lower() == "landscape")
    canvas_w = max(std_w, std_h) if is_landscape else min(std_w, std_h)
    canvas_h = min(std_w, std_h) if is_landscape else max(std_w, std_h)

    caps = get_printer_hardware_caps(printer_name, orientation, paper_size)
    l_m = float(caps.get("left_margin_pt", 12.0) or 12.0)
    r_m = float(caps.get("right_margin_pt", 12.0) or 12.0)
    t_m = float(caps.get("top_margin_pt", 12.0) or 12.0)
    b_m = float(caps.get("bottom_margin_pt", 12.0) or 12.0)

    avail_w = max(10.0, canvas_w - (l_m + r_m))
    avail_h = max(10.0, canvas_h - (t_m + b_m))

    img = Image.open(str(image_path))
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        bg.paste(img, mask=img.split()[3])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # Rotate image content to align with requested orientation
    if is_landscape and img.height > img.width:
        img = img.rotate(270, expand=True)
    elif not is_landscape and img.width > img.height:
        img = img.rotate(270, expand=True)

    img_w, img_h = img.size
    is_fill = (str(scale_mode).lower() in ("fill", "cover"))

    if is_fill:
        s = max(avail_w / max(1, img_w), avail_h / max(1, img_h))
        draw_w = img_w * s
        draw_h = img_h * s
        draw_x = l_m + (avail_w - draw_w) / 2.0
        draw_y = b_m + (avail_h - draw_h) / 2.0
    else:  # fit / full_page
        # Fit into available printable area with controlled ~4% expansion toward physical borders
        base_s = min(avail_w / max(1, img_w), avail_h / max(1, img_h))
        max_limit_s = min((canvas_w - 4.0) / max(1, img_w), (canvas_h - 4.0) / max(1, img_h))
        s = min(base_s * 1.04, max_limit_s)
        draw_w = img_w * s
        draw_h = img_h * s
        draw_x = (canvas_w - draw_w) / 2.0
        draw_y = (canvas_h - draw_h) / 2.0

    has_reportlab = False
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.utils import ImageReader
        has_reportlab = True
    except Exception as rl_err:
        print(f"[IMAGE TO PDF REPORTLAB WARNING]: {rl_err}. Falling back to native PIL PDF rendering.")

    if has_reportlab:
        temp_rgb_path = out_pdf_path.parent / f"tmp_rgb_{out_pdf_path.stem}.jpg"
        img.save(temp_rgb_path, "JPEG", quality=95)

        try:
            c = canvas.Canvas(str(out_pdf_path), pagesize=(canvas_w, canvas_h))
            if is_fill:
                c.saveState()
                clip_path = c.beginPath()
                clip_path.rect(l_m, b_m, avail_w, avail_h)
                c.clipPath(clip_path, stroke=0)
                c.drawImage(ImageReader(str(temp_rgb_path)), draw_x, draw_y, width=draw_w, height=draw_h)
                c.restoreState()
            else:
                c.drawImage(ImageReader(str(temp_rgb_path)), draw_x, draw_y, width=draw_w, height=draw_h)
            c.showPage()
            c.save()
        finally:
            if temp_rgb_path.exists():
                try:
                    temp_rgb_path.unlink()
                except Exception:
                    pass
    else:
        # High-fidelity native PIL direct PDF export (zero external dependency required)
        dpi = 300
        canvas_px_w = int(canvas_w / 72.0 * dpi)
        canvas_px_h = int(canvas_h / 72.0 * dpi)
        draw_px_w = max(1, int(draw_w / 72.0 * dpi))
        draw_px_h = max(1, int(draw_h / 72.0 * dpi))
        # Note: PIL image coordinates are top-left origin, PDF coordinates are bottom-left
        draw_px_x = int(draw_x / 72.0 * dpi)
        draw_px_y = int((canvas_h - (draw_y + draw_h)) / 72.0 * dpi)

        base_sheet = Image.new("RGB", (canvas_px_w, canvas_px_h), (255, 255, 255))
        resized_img = img.resize((draw_px_w, draw_px_h), Image.Resampling.LANCZOS)
        base_sheet.paste(resized_img, (draw_px_x, draw_px_y))
        base_sheet.save(str(out_pdf_path), "PDF", resolution=float(dpi))

    return out_pdf_path

def convert_text_to_pdf(
    txt_path: Path,
    out_pdf_path: Path,
    orientation: str = "portrait",
    paper_size: str = "a4"
) -> Path:
    from reportlab.pdfgen import canvas

    paper_map = {
        "a4": (595.276, 841.890),
        "letter": (612.0, 792.0),
        "legal": (612.0, 1008.0)
    }
    std_w, std_h = paper_map.get(paper_size.lower(), (595.276, 841.890))
    is_landscape = (str(orientation).lower() == "landscape")
    canvas_w = max(std_w, std_h) if is_landscape else min(std_w, std_h)
    canvas_h = min(std_w, std_h) if is_landscape else max(std_w, std_h)

    margin = 36.0
    font_name = "Helvetica"
    font_size = 10
    line_height = 14

    lines = txt_path.read_text(encoding="utf-8", errors="replace").splitlines()

    c = canvas.Canvas(str(out_pdf_path), pagesize=(canvas_w, canvas_h))
    y = canvas_h - margin - font_size
    c.setFont(font_name, font_size)

    for line in lines:
        if y < margin + font_size:
            c.showPage()
            c.setFont(font_name, font_size)
            y = canvas_h - margin - font_size
        c.drawString(margin, y, line[:120])
        y -= line_height

    c.showPage()
    c.save()
    return out_pdf_path

def compose_manifest_to_pdf(
    claimed_order: dict,
    backend_url: str,
    agent_token: str,
    target_printer: str
) -> Path:
    import pypdf

    order_id = claimed_order.get("order_id", "order")
    files_list = claimed_order.get("files") or []
    default_path = claimed_order.get("file_path", "")
    default_name = claimed_order.get("file_name", "document.pdf")
    orientation = claimed_order.get("orientation") or "mixed"
    paper_size = claimed_order.get("paper_size", "a4")
    scale_mode = claimed_order.get("scale_mode", "fit")
    print_mode = claimed_order.get("print_mode", "standard")
    pages_per_sheet = int(claimed_order.get("pages_per_sheet", 1))
    page_order = claimed_order.get("page_order", "horizontal")
    page_range = claimed_order.get("page_range", "all") or "all"
    duplex = claimed_order.get("duplex", "single")
    color_mode = claimed_order.get("color_mode", "black_white")
    is_color = str(color_mode).lower() in ("color", "colour")

    if not files_list:
        if default_path:
            files_list = [{"name": default_name, "path": default_path, "pages": claimed_order.get("pages", 1), "sequence": 0}]
        else:
            raise ValueError(f"Order {order_id} has no files or file_path")

    files_list = sorted(files_list, key=lambda f: f.get("sequence", 0))

    normalized_pdf_pages = []
    base_stem = re.sub(r'[^a-zA-Z0-9_\-]+', '_', order_id).strip('_') or 'job'
    order_work_dir = TEMP_DOWNLOAD_DIR / f"work_{base_stem}"
    order_work_dir.mkdir(parents=True, exist_ok=True)

    print(f"[COMPOSITOR] Processing order {order_id} with {len(files_list)} file(s)...")

    for f_idx, item in enumerate(files_list):
        f_name = item.get("name") or f"file_{f_idx+1}"
        f_path_rel = item.get("path") or item.get("file_path") or ""
        if not f_path_rel:
            continue

        print(f"[COMPOSITOR] [{f_idx+1}/{len(files_list)}] Downloading '{f_name}' ({f_path_rel})...")
        local_file = download_file(backend_url, f_path_rel, agent_token, f_name)
        ext = local_file.suffix.lower()

        clean_item_stem = f"{f_idx:02d}_" + re.sub(r'[^a-zA-Z0-9_\-]+', '_', local_file.stem).strip('_')

        # Convert DOC/DOCX to PDF
        if ext in (".doc", ".docx"):
            word = None
            try:
                import win32com.client
                word = win32com.client.DispatchEx("Word.Application")
                word.Visible = False
                word.DisplayAlerts = 0
                doc = word.Documents.Open(str(local_file.resolve()), ReadOnly=True, ConfirmConversions=False)
                pdf_target = order_work_dir / f"{clean_item_stem}_word.pdf"
                try:
                    doc.SaveAs(str(pdf_target.resolve()), FileFormat=17)
                finally:
                    doc.Close(False)
                if pdf_target.exists():
                    local_file = pdf_target
                    ext = ".pdf"
            except Exception as w_err:
                print(f"[COMPOSITOR WORD COM WARNING]: {w_err}")
            finally:
                if word is not None:
                    try:
                        word.Quit()
                    except Exception:
                        pass

        f_orientation = item.get("orientation") or orientation
        f_paper_size = item.get("paper_size") or paper_size
        f_scale_mode = item.get("scale_mode") or scale_mode
        f_page_range = item.get("page_range") or (page_range if len(files_list) == 1 else "all")
        f_duplex = item.get("duplex") or duplex
        is_item_duplex = (not is_color) and (f_duplex in (
            "duplex_long", "duplex_short", "duplexlong", "duplexshort",
            "long_edge", "short_edge", "double", "duplex", "vertical", "horizontal"
        ))

        # Convert Image to PDF
        if ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
            img_pdf = order_work_dir / f"{clean_item_stem}_img.pdf"
            convert_image_to_pdf_page(
                local_file,
                img_pdf,
                orientation=f_orientation,
                paper_size=f_paper_size,
                scale_mode=f_scale_mode,
                printer_name=target_printer
            )
            local_file = img_pdf
            ext = ".pdf"

        # Convert TXT to PDF
        if ext == ".txt":
            txt_pdf = order_work_dir / f"{clean_item_stem}_txt.pdf"
            convert_text_to_pdf(
                local_file,
                txt_pdf,
                orientation=f_orientation,
                paper_size=f_paper_size
            )
            local_file = txt_pdf
            ext = ".pdf"

        if ext == ".pdf":
            if f_page_range and str(f_page_range).strip().lower() != "all":
                local_file = extract_pdf_page_subset(local_file, f_page_range)

            optimized_pdf = optimize_pdf_for_full_page(
                local_file,
                paper_size=f_paper_size,
                orientation=f_orientation,
                scale_mode=f_scale_mode,
                printer_name=target_printer
            )

            r = pypdf.PdfReader(str(optimized_pdf))
            item_pages = list(r.pages)
            print(f"[COMPOSITOR] Adding {len(item_pages)} page(s) from '{f_name}'")
            for p in item_pages:
                normalized_pdf_pages.append(p)

            # Duplex boundary: if this item is duplex and has an odd number of pages,
            # and there are subsequent files in this merged stream, append a blank page
            # so the next file starts on a fresh physical sheet!
            if is_item_duplex and (len(item_pages) % 2 != 0) and (f_idx < len(files_list) - 1):
                last_p = item_pages[-1]
                last_w = float(last_p.mediabox.width)
                last_h = float(last_p.mediabox.height)
                boundary_writer = pypdf.PdfWriter()
                boundary_writer.add_blank_page(width=last_w, height=last_h)
                boundary_pdf_path = order_work_dir / f"{clean_item_stem}_boundary_blank.pdf"
                with open(boundary_pdf_path, "wb") as bf:
                    boundary_writer.write(bf)
                boundary_reader = pypdf.PdfReader(str(boundary_pdf_path))
                normalized_pdf_pages.append(boundary_reader.pages[0])
                print(f"[COMPOSITOR DUPLEX BOUNDARY] Added blank backside page after '{f_name}' ({len(item_pages)} pages) so next file starts on a fresh sheet.")
        else:
            print(f"[COMPOSITOR WARNING] Unsupported file format '{ext}' for file '{f_name}'")

    if not normalized_pdf_pages:
        raise RuntimeError(f"No printable pages generated from manifest for order {order_id}")

    inter_pdf = order_work_dir / "intermediate_merged.pdf"
    writer = pypdf.PdfWriter()
    for page in normalized_pdf_pages:
        writer.add_page(page)
    with open(inter_pdf, "wb") as f_out:
        writer.write(f_out)

    target_composed_file = inter_pdf

    if str(print_mode).lower() == "micro_xerox" or pages_per_sheet > 1:
        target_nup = pages_per_sheet if pages_per_sheet > 1 else 2
        nup_pdf = create_n_up_pdf(
            target_composed_file,
            target_nup,
            page_order,
            paper_size=paper_size,
            orientation=orientation,
            printer_name=target_printer
        )
        target_composed_file = nup_pdf

    is_micro_xerox = (str(print_mode).lower() == "micro_xerox" or pages_per_sheet > 1)
    is_duplex_job = (not is_color) and (duplex in (
        "duplex_long", "duplex_short", "duplexlong", "duplexshort",
        "long_edge", "short_edge", "double", "duplex", "vertical", "horizontal"
    ))

    if not is_color and not is_micro_xerox and is_duplex_job:
        reader = pypdf.PdfReader(str(target_composed_file))
        source_pages = len(reader.pages)
        canonical_duplex_log = "duplex_short" if duplex in ("duplex_short", "duplexshort", "short_edge", "short", "horizontal") else "duplex_long"

        if source_pages % 2 != 0:
            d_writer = pypdf.PdfWriter()
            for p in reader.pages:
                d_writer.add_page(p)
            last_p = reader.pages[-1]
            last_w = float(last_p.mediabox.width)
            last_h = float(last_p.mediabox.height)
            d_writer.add_blank_page(width=last_w, height=last_h)

            padded_pdf = order_work_dir / "composed_duplex_even.pdf"
            with open(padded_pdf, "wb") as f_out:
                d_writer.write(f_out)

            target_composed_file = padded_pdf
            final_pages = source_pages + 1

            print("")
            print("[FINAL DUPLEX DOCUMENT]")
            print(f"source_pages={source_pages}")
            print(f"final_pages={final_pages}")
            print(f"duplex={canonical_duplex_log}")
            print("trailing_blank_page=true")
            print("")
        else:
            print("")
            print("[FINAL DUPLEX DOCUMENT]")
            print(f"source_pages={source_pages}")
            print(f"final_pages={source_pages}")
            print(f"duplex={canonical_duplex_log}")
            print("trailing_blank_page=false")
            print("")

    final_dest = TEMP_DOWNLOAD_DIR / f"final_printready_{base_stem}.pdf"
    shutil.copy2(target_composed_file, final_dest)
    return final_dest

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
    page_range: str = "all",
    print_mode: str = "standard",
    already_composed: bool = False
) -> int:
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

    if str(print_mode).lower() == "micro_xerox" and is_color:
        is_color = False
        color_mode = "black_white"

    if not already_composed:
        # Convert DOC / DOCX to PDF via Word COM if available
        if ext in (".doc", ".docx"):
            word = None
            try:
                import win32com.client
                word = win32com.client.DispatchEx("Word.Application")
                word.Visible = False
                word.DisplayAlerts = 0
                doc = word.Documents.Open(str(file_path.resolve()), ReadOnly=True, ConfirmConversions=False)
                try:
                    pdf_path = file_path.parent / f"{file_path.stem}.pdf"
                    doc.SaveAs(str(pdf_path.resolve()), FileFormat=17)
                finally:
                    doc.Close(False)
                if pdf_path.exists():
                    target_print_file = pdf_path
                    ext = ".pdf"
            except Exception as word_err:
                print("[AGENT WORD COM EXPORT WARNING]:", word_err)
            finally:
                if word is not None:
                    try:
                        word.Quit()
                    except Exception:
                        pass

        # Universal Image-to-PDF Conversion
        if is_image:
            try:
                img_pdf = target_print_file.parent / f"{target_print_file.stem}_img.pdf"
                convert_image_to_pdf_page(
                    target_print_file,
                    img_pdf,
                    orientation=orientation,
                    paper_size=paper_size,
                    scale_mode=scale_mode,
                    printer_name=printer_name
                )
                if img_pdf.exists():
                    target_print_file = img_pdf
                    ext = ".pdf"
            except Exception as img_conv_err:
                print("[AGENT IMAGE CONVERT TO PDF WARNING]:", img_conv_err)

        if ext == ".pdf" and page_range and str(page_range).strip().lower() != "all":
            target_print_file = extract_pdf_page_subset(target_print_file, page_range)

        if ext == ".pdf" and (str(print_mode).lower() == "micro_xerox" or pages_per_sheet > 1):
            target_nup = pages_per_sheet if pages_per_sheet > 1 else 2
            target_print_file = create_n_up_pdf(
                target_print_file,
                target_nup,
                page_order,
                paper_size=paper_size,
                orientation=orientation,
                printer_name=printer_name
            )
        elif ext == ".pdf":
            target_print_file = optimize_pdf_for_full_page(
                target_print_file,
                paper_size=paper_size,
                orientation=orientation,
                scale_mode=scale_mode,
                printer_name=printer_name
            )

        is_micro_xerox = (str(print_mode).lower() == "micro_xerox" or pages_per_sheet > 1)
        is_duplex_job = (not is_color) and (duplex in (
            "duplex_long", "duplex_short", "duplexlong", "duplexshort",
            "long_edge", "short_edge", "double", "duplex", "vertical", "horizontal"
        ))

        if ext == ".pdf" and not is_color and not is_micro_xerox and is_duplex_job:
            import pypdf
            reader = pypdf.PdfReader(str(target_print_file))
            source_pages = len(reader.pages)
            canonical_duplex_log = "duplex_short" if duplex in ("duplex_short", "duplexshort", "short_edge", "short", "horizontal") else "duplex_long"

            if source_pages % 2 != 0:
                writer = pypdf.PdfWriter()
                for p in reader.pages:
                    writer.add_page(p)
                last_page = reader.pages[-1]
                last_w = float(last_page.mediabox.width)
                last_h = float(last_page.mediabox.height)
                writer.add_blank_page(width=last_w, height=last_h)

                clean_stem = re.sub(r'[^a-zA-Z0-9_\-]+', '_', target_print_file.stem).strip('_')
                duplex_pdf_path = target_print_file.parent / f"{clean_stem}_duplex_even.pdf"
                with open(duplex_pdf_path, "wb") as f_out:
                    writer.write(f_out)

                target_print_file = duplex_pdf_path
                final_pages = source_pages + 1

                print("")
                print("[FINAL DUPLEX DOCUMENT]")
                print(f"source_pages={source_pages}")
                print(f"final_pages={final_pages}")
                print(f"duplex={canonical_duplex_log}")
                print("trailing_blank_page=true")
                print("")
            else:
                print("")
                print("[FINAL DUPLEX DOCUMENT]")
                print(f"source_pages={source_pages}")
                print(f"final_pages={source_pages}")
                print(f"duplex={canonical_duplex_log}")
                print("trailing_blank_page=false")
                print("")

    # Diagnostic Logs before physical printing
    paper_str = "A4" if paper_size.lower() == "a4" else paper_size.upper()
    color_str = "bw" if not is_color else "color"
    duplex_str = "single" if (is_color or duplex == "single") else "double"
    scale_str = "fit" if scale_mode not in ("actual", "actual_size") else "actual_size"
    page_size_str = "297x210mm" if orientation.lower() == "landscape" else "210x297mm"

    print("")
    print("[PRINT CONFIG]")
    print(f"orientation={orientation.lower()}")
    print(f"paper={paper_str}")
    print(f"color_mode={color_str}")
    print(f"duplex={duplex_str}")
    print(f"scale_mode={scale_str}")
    print("")
    print("[PRINT DOCUMENT]")
    print(f"page_size={page_size_str}")
    print(f"orientation={orientation.lower()}")
    print("")
    print("[PHYSICAL PRINT]")
    print(f"printer={printer_name}")
    print(f"orientation={orientation.lower()}")
    print("")
    caps = get_printer_hardware_caps(printer_name, orientation, paper_size)
    log_printer_margins(caps)
    print("")

    if ext == ".pdf":
        import pypdf
        v_reader = pypdf.PdfReader(str(target_print_file))
        actual_pages = len(v_reader.pages)
        print(f"[FINAL PRINT-READY PDF] file={target_print_file.name}, pages={actual_pages}")
        for p_idx, p in enumerate(v_reader.pages):
            pw = float(p.mediabox.width)
            ph = float(p.mediabox.height)
            print(f"[FINAL PDF VALIDATION] Page {p_idx+1}/{actual_pages}: {pw:.1f}x{ph:.1f} pt")

    # Linux / CUPS fallback
    if sys.platform != "win32":
        lp = shutil.which("lp")
        if lp:
            cmd = [lp, "-d", printer_name, "-n", str(copies), str(target_print_file)]
            subprocess.run(cmd, check=True, timeout=15)
            return 0
        return 0

    # Windows PDF silent execution with SumatraPDF
    sumatra = find_sumatra_executable()
    if ext == ".pdf" and sumatra:
        # Pre-configure Windows Printer DEVMODE (ensures hardware driver is initialized for Color or Monochrome)
        if sys.platform == "win32":
            try:
                import win32print, win32con
                hprinter = win32print.OpenPrinter(printer_name, {"DesiredAccess": win32print.PRINTER_ALL_ACCESS})
                try:
                    pinfo = win32print.GetPrinter(hprinter, 2)
                    devmode = pinfo.get("pDevMode")
                    if devmode:
                        # 1 = MONOCHROME, 2 = COLOR
                        devmode.Color = 2 if is_color else 1
                        devmode.Fields |= win32con.DM_COLOR
                        devmode.Orientation = 2 if orientation.lower() == "landscape" else 1
                        devmode.Fields |= win32con.DM_ORIENTATION
                        paper_map_dm = {"a4": 9, "letter": 1, "legal": 5}
                        devmode.PaperSize = paper_map_dm.get(paper_size.lower(), 9)
                        devmode.Fields |= win32con.DM_PAPERSIZE
                        if is_color or duplex == "single":
                            devmode.Duplex = 1
                        elif duplex in ("duplex_short", "duplexshort", "short_edge", "short", "horizontal"):
                            devmode.Duplex = 3
                        elif duplex in ("duplex_long", "duplexlong", "long_edge", "double", "duplex", "vertical"):
                            devmode.Duplex = 2
                        devmode.Fields |= win32con.DM_DUPLEX
                        win32print.SetPrinter(hprinter, 2, pinfo, 0)
                        print(f"[DEVMODE CONFIG] Set {printer_name} -> dmColor={'2 (COLOR)' if is_color else '1 (MONO)'}, dmDuplex={devmode.Duplex}")
                finally:
                    win32print.ClosePrinter(hprinter)
            except Exception as dm_err:
                print(f"[PRINTER DEVMODE CONFIG WARNING]: {dm_err}")

        settings_parts = ["noscale"]

        # Duplex (Sumatra keyword is "simplex", "duplexshort", or "duplexlong")
        if is_color or duplex == "single":
            settings_parts.append("simplex")
        elif duplex in ("duplex_short", "duplexshort", "short_edge", "short", "horizontal"):
            settings_parts.append("duplexshort")
        elif duplex in ("duplex_long", "duplexlong", "long_edge", "double", "duplex", "vertical"):
            settings_parts.append("duplexlong")
        else:
            settings_parts.append("simplex")

        # Orientation
        if orientation.lower() == "landscape":
            settings_parts.append("landscape")
        else:
            settings_parts.append("portrait")

        # Paper size
        paper_map = {"a4": "a4", "letter": "letter", "legal": "legal"}
        pname = paper_map.get(paper_size.lower(), "a4")
        settings_parts.append(f"paper={pname}")
        settings_parts.append(f"{max(1, copies)}x")

        # Color mode:
        # SumatraPDF natively supports "monochrome". When printing Color, omit "monochrome"
        # and allow the Windows DEVMODE (dmColor = 2) to render in full vibrant color.
        if not is_color:
            settings_parts.append("monochrome")

        settings_str = ",".join(settings_parts)

        cmd = [sumatra, "-print-to", printer_name, "-print-settings", settings_str, "-silent", str(target_print_file.resolve())]
        print(f"[SUMATRA COMMAND] {' '.join(cmd)}")

        before_job_ids = set()
        if sys.platform == "win32":
            try:
                import win32print
                hprinter = win32print.OpenPrinter(printer_name)
                try:
                    jobs = win32print.EnumJobs(hprinter, 0, 999, 2)
                    before_job_ids = {j["JobId"] for j in jobs}
                finally:
                    win32print.ClosePrinter(hprinter)
            except Exception as e:
                print(f"[SPOOLER PRE-ENUM WARNING]: {e}")

        subprocess.run(cmd, check=True, timeout=45)

        spooler_job_id = 0
        if sys.platform == "win32":
            try:
                import win32print
                hprinter = win32print.OpenPrinter(printer_name)
                try:
                    for _ in range(15):
                        current_jobs = win32print.EnumJobs(hprinter, 0, 999, 2)
                        new_jobs = [j for j in current_jobs if j["JobId"] not in before_job_ids]
                        if new_jobs:
                            spooler_job_id = new_jobs[0]["JobId"]
                            break
                        time.sleep(0.2)
                finally:
                    win32print.ClosePrinter(hprinter)
            except Exception as e:
                print(f"[SPOOLER DETECTION WARNING]: {e}")

        if spooler_job_id > 0:
            print(f"[SPOOLER TRACKING] Detected Spooler Job ID: {spooler_job_id} on '{printer_name}'")
        else:
            print(f"[SPOOLER TRACKING] Job submitted to '{printer_name}' (completed spooling or processed directly)")

        time.sleep(1.0)
        return spooler_job_id

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

            # Preserve upright image content without forced 90-degree rotation
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

                if scale_mode in ("actual", "actual_size"):
                    scale = min(1.0, printable_width / max(1, img_w), printable_height / max(1, img_h))
                else:
                    scale = min(printable_width / max(1, img_w), printable_height / max(1, img_h))
                new_w = int(img_w * scale)
                new_h = int(img_h * scale)
                x = (printable_width - new_w) // 2
                y = (printable_height - new_h) // 2

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
        word = None
        try:
            import win32com.client
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0
            doc = word.Documents.Open(str(target_print_file.resolve()), ReadOnly=True, ConfirmConversions=False)
            try:
                word.ActivePrinter = printer_name
                doc.PrintOut(Copies=copies)
            finally:
                doc.Close(False)
            return True
        except Exception as word_err:
            print("[AGENT WORD COM WARNING]:", word_err)
        finally:
            if word is not None:
                try:
                    word.Quit()
                except Exception:
                    pass

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

                if not order_id:
                    continue

                files_manifest = job.get("files") or []
                if not file_rel_path and files_manifest:
                    file_rel_path = files_manifest[0].get("path") or files_manifest[0].get("file_path") or ""

                if not file_rel_path and not files_manifest:
                    print(f"[AGENT POLL WARNING] Order {order_id} has empty file path and manifest. Marking failed.")
                    update_order_agent_status(backend_url, agent_token, order_id, "FAILED", error="Empty file path")
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

                claimed_order = job
                try:
                    with urllib.request.urlopen(claim_req, timeout=10) as claim_resp:
                        claim_res = json.loads(claim_resp.read().decode("utf-8"))
                        if claim_res.get("status") != "success":
                            print(f"[AGENT CLAIM REJECTED] Order {order_id} already claimed by another worker.")
                            continue
                        if claim_res.get("order"):
                            claimed_order = claim_res["order"]
                except urllib.error.HTTPError as http_err:
                    if http_err.code == 409:
                        print(f"[AGENT CLAIM REJECTED] Order {order_id} already claimed by another worker.")
                        continue
                    print(f"[AGENT CLAIM ERROR] Skipping order {order_id}:", http_err)
                    continue
                except Exception as claim_err:
                    print(f"[AGENT CLAIM ERROR] Skipping order {order_id}:", claim_err)
                    continue

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
                if str(print_mode).lower() == "micro_xerox":
                    is_color = False
                    color_mode = "black_white"
                file_name = claimed_order.get("file_name", file_name)

                target_printer = select_target_printer(color_mode, config, installed_printers)
                p_info = next((p for p in installed_printers if p["name"] == target_printer), None)

                # Preflight Check 1: Target printer online
                if p_info and not p_info.get("online", True):
                    err_msg = f"Target printer '{target_printer}' is offline. Job will remain queued."
                    print(f"[PREFLIGHT FAILED] {err_msg}")
                    update_order_agent_status(backend_url, agent_token, order_id, "FAILED", error=err_msg, printed_by_printer=target_printer)
                    continue

                # Preflight Check 2: Hardware duplex support (REJECT, NO SILENT FALLBACK)
                is_duplex_job = (not is_color) and (duplex in (
                    "duplex_long", "duplex_short", "duplexlong", "duplexshort",
                    "long_edge", "short_edge", "double", "duplex", "vertical", "horizontal"
                ))
                if is_duplex_job and p_info and p_info.get("duplex_supported") is False:
                    err_msg = f"Duplex printing is not supported by the selected printer '{target_printer}'."
                    print(f"[PREFLIGHT FAILED] {err_msg}")
                    update_order_agent_status(backend_url, agent_token, order_id, "FAILED", error=err_msg, printed_by_printer=target_printer)
                    continue

                print(f"[AGENT CLAIMED] {order_id}, {target_printer}")
                print(f"[PRINT CONFIG] orientation={str(orientation).lower()}")

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

                    # Update status to PRINTING
                    update_order_agent_status(backend_url, agent_token, order_id, "PRINTING", printed_by_printer=target_printer)

                    # Check if multi-file order has heterogeneous duplex, copies, or color settings:
                    raw_files = claimed_order.get("files") or []
                    is_heterogeneous = False
                    if len(raw_files) > 1:
                        f0 = raw_files[0]
                        f0_duplex = f0.get("duplex") or duplex
                        f0_copies = int(f0.get("copies") or copies)
                        f0_color = f0.get("color_mode") or color_mode
                        f0_pm = (f0.get("print_mode") or "standard").lower()
                        f0_nup = int(f0.get("pages_per_sheet") or 1)
                        f0_orient = (f0.get("orientation") or orientation).lower()
                        f0_paper = (f0.get("paper_size") or paper_size).lower()
                        for f_it in raw_files[1:]:
                            it_duplex = f_it.get("duplex") or duplex
                            it_copies = int(f_it.get("copies") or copies)
                            it_color = f_it.get("color_mode") or color_mode
                            it_pm = (f_it.get("print_mode") or "standard").lower()
                            it_nup = int(f_it.get("pages_per_sheet") or 1)
                            it_orient = (f_it.get("orientation") or orientation).lower()
                            it_paper = (f_it.get("paper_size") or paper_size).lower()
                            if (it_duplex != f0_duplex or it_copies != f0_copies or it_color != f0_color or
                                it_pm != f0_pm or it_nup != f0_nup or it_orient != f0_orient or it_paper != f0_paper):
                                is_heterogeneous = True
                                break

                    if is_heterogeneous:
                        print(f"[AGENT SEGMENTATION] Order {order_id} has {len(raw_files)} heterogeneous files. Dispatching sequential spooler segments...")
                        for s_idx, f_seg in enumerate(raw_files):
                            s_copies = int(f_seg.get("copies") or 1)
                            s_duplex = f_seg.get("duplex") or duplex
                            s_color = f_seg.get("color_mode") or color_mode
                            s_orient = f_seg.get("orientation") or orientation
                            s_paper = f_seg.get("paper_size") or paper_size
                            s_scale = f_seg.get("scale_mode") or scale_mode
                            s_range = f_seg.get("page_range") or "all"
                            s_print_mode = f_seg.get("print_mode") or "standard"
                            s_nup = int(f_seg.get("pages_per_sheet") or 1)
                            s_order = f_seg.get("page_order") or "horizontal"

                            seg_claim = dict(claimed_order)
                            seg_claim["files"] = [f_seg]
                            seg_claim["file_name"] = f_seg.get("name", file_name)
                            seg_claim["file_path"] = f_seg.get("path", "")
                            seg_claim["copies"] = s_copies
                            seg_claim["duplex"] = s_duplex
                            seg_claim["color_mode"] = s_color
                            seg_claim["orientation"] = s_orient
                            seg_claim["paper_size"] = s_paper
                            seg_claim["scale_mode"] = s_scale
                            seg_claim["page_range"] = s_range
                            seg_claim["print_mode"] = s_print_mode
                            seg_claim["pages_per_sheet"] = s_nup
                            seg_claim["page_order"] = s_order

                            seg_target_printer = select_target_printer(s_color, config, installed_printers)
                            print(f"[AGENT SEGMENT {s_idx+1}/{len(raw_files)}] Processing '{f_seg.get('name')}' on '{seg_target_printer}' (copies={s_copies}, duplex={s_duplex}, color={s_color}, orient={s_orient}, mode={s_print_mode}, nup={s_nup})...")
                            seg_pdf = compose_manifest_to_pdf(seg_claim, backend_url, agent_token, seg_target_printer)
                            seg_job_id = print_document_silently(
                                seg_pdf,
                                seg_target_printer,
                                copies=s_copies,
                                orientation=s_orient,
                                color_mode=s_color,
                                duplex=s_duplex,
                                paper_size=s_paper,
                                scale_mode=s_scale,
                                pages_per_sheet=s_nup,
                                page_order=s_order,
                                page_range=s_range,
                                print_mode=s_print_mode,
                                already_composed=True
                            )
                            if seg_job_id > 0:
                                print(f"[AGENT SEGMENT {s_idx+1}] Spooled as Job #{seg_job_id} on '{seg_target_printer}'. Monitoring...")
                                monitor_spooler_job(backend_url, agent_token, order_id, seg_target_printer, seg_job_id)
                            else:
                                time.sleep(1)

                        update_order_agent_status(
                            backend_url, agent_token, order_id,
                            "COMPLETED",
                            spooler_job_id=0,
                            printed_by_printer=target_printer
                        )
                        print(f"[PRINT COMPLETED] {order_id} (all {len(raw_files)} segments)")
                    else:
                        # Homogenous order or single file
                        composed_pdf = compose_manifest_to_pdf(claimed_order, backend_url, agent_token, target_printer)
                        print(f"[AGENT COMPOSE] Final print-ready document: {composed_pdf.name}")

                        # Print silently with spooler capture
                        spooler_job_id = print_document_silently(
                            composed_pdf,
                            target_printer,
                            copies=copies,
                            orientation=orientation,
                            color_mode=color_mode,
                            duplex=duplex,
                            paper_size=paper_size,
                            scale_mode=scale_mode,
                            pages_per_sheet=pages_per_sheet,
                            page_order=page_order,
                            page_range=page_range,
                            print_mode=print_mode,
                            already_composed=True
                        )

                        if spooler_job_id > 0:
                            update_order_agent_status(
                                backend_url, agent_token, order_id,
                                "SUBMITTED_TO_SPOOLER",
                                spooler_job_id=spooler_job_id,
                                printed_by_printer=target_printer
                            )
                            monitor_spooler_job(backend_url, agent_token, order_id, target_printer, spooler_job_id)
                        else:
                            update_order_agent_status(
                                backend_url, agent_token, order_id,
                                "COMPLETED",
                                spooler_job_id=0,
                                printed_by_printer=target_printer
                            )
                            print(f"[PRINT COMPLETED] {order_id}")

                    # Privacy cleanup
                    try:
                        now_ts = time.time()
                        for tmp_f in TEMP_DOWNLOAD_DIR.glob("*"):
                            if tmp_f.is_file() and (now_ts - tmp_f.stat().st_mtime > 180):
                                try:
                                    tmp_f.unlink()
                                except Exception:
                                    pass
                            elif tmp_f.is_dir() and (now_ts - tmp_f.stat().st_mtime > 180):
                                try:
                                    shutil.rmtree(tmp_f, ignore_errors=True)
                                except Exception:
                                    pass
                    except Exception as c_err:
                        print(f"[AGENT LOCAL CLEANUP ERROR]: {c_err}")

                except Exception as print_err:
                    print(f"[AGENT PRINT ERROR] Order {order_id} printing failed: {print_err}")
                    update_order_agent_status(
                        backend_url, agent_token, order_id,
                        "FAILED",
                        error=str(print_err),
                        printed_by_printer=target_printer
                    )

        except Exception:
            pass

        time.sleep(poll_interval)

if __name__ == "__main__":
    run_agent()
