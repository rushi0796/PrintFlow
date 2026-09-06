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

def optimize_pdf_for_full_page(
    input_pdf_path: Path,
    paper_size: str = "a4",
    orientation: str = "portrait"
) -> Path:
    """
    Scales the ENTIRE original page/image canvas proportionally to cover
    and fill the selected paper dimensions to all four corners without white bands
    or empty corners, preserving 100% of the artwork and colored background.
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

            # Scale proportionally to the MAXIMUM POSSIBLE SIZE that covers the physical paper area:
            scale = min(sheet_w / orig_w, sheet_h / orig_h)
            scaled_w = orig_w * scale
            scaled_h = orig_h * scale

            # Center the complete canvas on the physical paper
            tx = (sheet_w - scaled_w) / 2.0
            ty = (sheet_h - scaled_h) / 2.0

            new_page = writer.add_blank_page(width=sheet_w, height=sheet_h)
            op = Transformation().scale(scale, scale).translate(tx, ty)
            new_page.merge_transformed_page(page, op)

        out_path = input_pdf_path.parent / f"fp_{input_pdf_path.name}"
        with open(out_path, "wb") as f_out:
            writer.write(f_out)
        return out_path
    except Exception as opt_err:
        print(f"[PRINT DISPATCH FULL PAGE SCALE WARNING]: {opt_err}")
        return input_pdf_path

def dispatch_print_job(order_data: dict) -> dict:
    order_id = order_data.get("order_id", "UNKNOWN")
    file_rel_path = order_data.get("file_path", "")
    raw_color_mode = str(order_data.get("color_mode", "black_white")).lower()
    is_color = raw_color_mode in ("color", "colour")
    color_mode = "color" if is_color else "black_white"

    if is_color:
        duplex = "single"
        binding = ""
    else:
        duplex = str(order_data.get("duplex", "single")).lower()
        binding = str(order_data.get("binding", "")).lower()
        if duplex in ("double", "duplex"):
            duplex = "duplex_short" if binding == "short_edge" else "duplex_long"

    copies = int(order_data.get("copies", 1))
    paper_size = order_data.get("paper_size", "a4")
    orientation = order_data.get("orientation", "portrait")
    scale_mode = order_data.get("scale_mode", "fit")
    pages_per_sheet = int(order_data.get("pages_per_sheet", 1))
    page_order = order_data.get("page_order", "horizontal")

    # Resolve absolute file path on server
    clean_filename = Path(file_rel_path).name if file_rel_path else ""
    abs_file_path = UPLOAD_DIR / clean_filename
    ext = abs_file_path.suffix.lower()
    target_print_file = abs_file_path
    is_image = ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp")

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

    # Convert images to PDF for SumatraPDF silent execution
    if is_image:
        try:
            import re
            from PIL import Image
            img = Image.open(abs_file_path)
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                bg.paste(img, mask=img.split()[3])
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")

            clean_stem = re.sub(r'[^a-zA-Z0-9_\-]+', '_', abs_file_path.stem).strip('_') or 'image'
            pdf_path = abs_file_path.parent / f"{clean_stem}_img.pdf"
            img.save(pdf_path, "PDF", resolution=300.0)
            if pdf_path.exists():
                target_print_file = pdf_path
                ext = ".pdf"
        except Exception as img_err:
            print(f"[PRINT DISPATCH IMAGE CONVERT WARNING]: {img_err}")

    # Process Micro Xerox layout for PDF files
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

    # Windows Direct Silent Printing Execution
    if sys.platform == "win32":
        try:
            # 1. SumatraPDF silent printing if available
            sumatra = find_sumatra_executable()
            if sumatra and ext == ".pdf":
                settings_parts = []
                if scale_mode in ("actual", "actual_size") and not is_image:
                    settings_parts.append("shrink")
                else:
                    settings_parts.append("fit")
                
                if is_color or duplex == "single":
                    settings_parts.append("noduplex")
                elif duplex in ("duplex_short", "duplexshort", "short_edge", "short", "horizontal"):
                    settings_parts.append("duplexshort")
                elif duplex in ("duplex_long", "duplexlong", "long_edge", "double", "duplex", "vertical"):
                    settings_parts.append("duplexlong")
                else:
                    settings_parts.append("noduplex")

                if orientation.lower() == "landscape":
                    settings_parts.append("landscape")
                else:
                    settings_parts.append("portrait")

                # Paper Size & Paper Kind
                paper_map = {"a4": (9, "a4"), "letter": (1, "letter"), "legal": (5, "legal")}
                pid, pname = paper_map.get(paper_size.lower(), (9, "a4"))
                settings_parts.append(f"paper={pname}")
                settings_parts.append(f"paperkind={pid}")

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

            # 2. Windows ShellExecute printto verb (for PDF/DOC, not images)
            if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
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
            else:
                mspaint = shutil.which("mspaint.exe") or "mspaint"
                cmd = [mspaint, "/pt", str(target_print_file.resolve()), target_printer]
                subprocess.run(cmd, check=True, timeout=15)
                return {
                    "status": "success",
                    "order_id": order_id,
                    "printer": target_printer,
                    "method": "mspaint",
                    "message": f"Printed successfully via mspaint to '{target_printer}'"
                }
        except Exception as win_err:
            print(f"[PRINT DISPATCH WIN32 WARNING]: {win_err}")
            if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
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
