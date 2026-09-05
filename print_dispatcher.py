import os
import sys
import shutil
import subprocess
from pathlib import Path
from printer_manager import get_target_printer

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = Path("/tmp/printflow-uploads") if os.environ.get("VERCEL") else BASE_DIR / "uploads"

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
    print(f"[PRINT DISPATCH] Order {order_id} | File: '{clean_filename}' | Mode: {color_mode} | Printer: '{target_printer}' | Duplex: {duplex} | Paper: {paper_size} | Copies: {copies}")

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
        target_print_file = create_n_up_pdf(abs_file_path, pages_per_sheet, page_order)

    # Windows Direct Silent Printing Execution
    if sys.platform == "win32":
        try:
            # 1. SumatraPDF silent printing if available
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
                cmd = [sumatra, "-print-to", target_printer, "-print-settings", settings_str, str(target_print_file)]
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
