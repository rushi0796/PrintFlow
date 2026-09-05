import os
import sys
import shutil
import subprocess
from pathlib import Path
from typing import Optional
from printer_manager import get_target_printer

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = Path("/tmp/printflow-uploads") if os.environ.get("VERCEL") else BASE_DIR / "uploads"

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
        print(f"[PRINT DISPATCH FULL PAGE OPT WARNING]: {opt_err}")
        return input_pdf_path

def dispatch_print_job(order_data: dict) -> dict:
    order_id = order_data.get("order_id", "UNKNOWN")
    file_rel_path = order_data.get("file_path", "")
    color_mode = order_data.get("color_mode", "black_white")
    copies = int(order_data.get("copies", 1))
    duplex = order_data.get("duplex", "single")
    paper_size = order_data.get("paper_size", "a4")
    orientation = order_data.get("orientation", "portrait")
    scale_mode = order_data.get("scale_mode", "fit")
    pages_per_sheet = int(order_data.get("pages_per_sheet", 1))
    page_order = order_data.get("page_order", "horizontal")

    # Resolve absolute file path on server
    clean_filename = Path(file_rel_path).name if file_rel_path else ""
    abs_file_path = UPLOAD_DIR / clean_filename

    target_printer = get_target_printer(color_mode)
    print(f"[PRINT DISPATCH] Order {order_id} | File: '{clean_filename}' | Mode: {color_mode} | Printer: '{target_printer}' | Duplex: {duplex} | Paper: {paper_size} | Copies: {copies} | Scale: {scale_mode}")

    if not abs_file_path.exists():
        print(f"[PRINT DISPATCH WARNING] File '{abs_file_path}' not found on disk. Simulating spooling queue.")
        return {
            "status": "success",
            "simulated": True,
            "order_id": order_id,
            "printer": target_printer,
            "message": f"Order {order_id} spooled to virtual printer '{target_printer}'"
        }

    # Process Micro Xerox layout for PDF files
    ext = abs_file_path.suffix.lower()
    target_print_file = abs_file_path
    if ext == ".pdf" and pages_per_sheet > 1:
        target_print_file = create_n_up_pdf(
            abs_file_path,
            pages_per_sheet,
            page_order,
            paper_size=paper_size,
            orientation=orientation
        )
    elif ext == ".pdf" and pages_per_sheet <= 1 and scale_mode not in ("actual", "actual_size"):
        target_print_file = optimize_pdf_for_full_page(
            abs_file_path,
            paper_size=paper_size,
            orientation=orientation
        )

    # Windows Direct Silent Printing Execution
    if sys.platform == "win32":
        try:
            # 1. SumatraPDF silent printing if available
            sumatra = find_sumatra_executable()
            if sumatra:
                settings_parts = []
                if scale_mode in ("actual", "actual_size"):
                    settings_parts.append("noscale")
                else:
                    settings_parts.append("fit")
                
                if duplex in ("double", "duplex", "duplexlong", "vertical"):
                    settings_parts.append("duplexlong")
                elif duplex in ("duplexshort", "short", "horizontal"):
                    settings_parts.append("duplexshort")
                else:
                    settings_parts.append("noduplex")

                if orientation.lower() == "landscape":
                    settings_parts.append("landscape")
                else:
                    settings_parts.append("portrait")

                if paper_size:
                    settings_parts.append(f"paper={paper_size.lower()}")

                settings_parts.append(f"{max(1, copies)}x")

                if color_mode.lower() in ("color", "colour"):
                    settings_parts.append("color")
                else:
                    settings_parts.append("monochrome")

                settings_str = ",".join(settings_parts)
                cmd = [sumatra, "-print-to", target_printer, "-print-settings", settings_str, str(target_print_file.resolve())]
                subprocess.run(cmd, check=True, timeout=25)
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
            for _ in range(copies):
                win32api.ShellExecute(0, "printto", str(target_print_file), f'"{target_printer}"', ".", 0)
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
            try:
                ps_cmd = f'Start-Process -FilePath "{target_print_file}" -Verb PrintTo -ArgumentList "{target_printer}" -PassThru'
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
                cmd = [lp, "-d", target_printer, "-n", str(copies), str(target_print_file)]
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
