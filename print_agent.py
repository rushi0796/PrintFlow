import os
import sys
import json
import time
import shutil
import urllib.request
import subprocess
from pathlib import Path


# ============================================================
# PRINTFLOW LOCAL WINDOWS PRINT AGENT
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

CONFIG_FILE = BASE_DIR / "agent_config.json"
EXAMPLE_CONFIG_FILE = BASE_DIR / "agent_config.example.json"

TEMP_DOWNLOAD_DIR = BASE_DIR / "agent_temp"
TEMP_DOWNLOAD_DIR.mkdir(exist_ok=True)


# ============================================================
# CONFIG
# ============================================================

def load_agent_config():
    if not CONFIG_FILE.exists():

        if EXAMPLE_CONFIG_FILE.exists():
            shutil.copy(EXAMPLE_CONFIG_FILE, CONFIG_FILE)

        else:
            default_data = {
                "backend_url": "https://print-flow-mu.vercel.app",
                "agent_token": "PF_AGENT_SECRET_TOKEN_2026",
                "poll_interval_seconds": 3,
                "bw_printer": "Kyocera ECOSYS M2040dn KX",
                "color_printer": "EPSON L3210 Series",
                "auto_routing": True
            }

            CONFIG_FILE.write_text(
                json.dumps(default_data, indent=2),
                encoding="utf-8"
            )

    try:
        return json.loads(
            CONFIG_FILE.read_text(encoding="utf-8")
        )

    except Exception as err:
        print("[AGENT CONFIG ERROR]:", err)

        return {
            "backend_url": "https://print-flow-mu.vercel.app",
            "agent_token": "PF_AGENT_SECRET_TOKEN_2026",
            "poll_interval_seconds": 3,
            "bw_printer": "Kyocera ECOSYS M2040dn KX",
            "color_printer": "EPSON L3210 Series",
            "auto_routing": True
        }


# ============================================================
# WINDOWS PRINTER DISCOVERY
# ============================================================

def get_installed_windows_printers():

    printers = []

    if sys.platform == "win32":

        try:

            ps_cmd = (
                "Get-Printer | "
                "Select-Object Name, DriverName, PrinterStatus, IsDefault | "
                "ConvertTo-Json"
            )

            res = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    ps_cmd
                ],
                capture_output=True,
                text=True,
                timeout=10
            )

            if res.returncode == 0 and res.stdout.strip():

                data = json.loads(res.stdout)

                if isinstance(data, dict):
                    data = [data]

                for p in data:

                    printers.append({
                        "name": p.get("Name", ""),
                        "driver": p.get("DriverName", ""),
                        "status": (
                            "Normal"
                            if p.get("PrinterStatus") in (0, "Normal", None)
                            else str(p.get("PrinterStatus"))
                        ),
                        "is_default": bool(
                            p.get("IsDefault")
                        )
                    })

        except Exception as e:

            print(
                "[AGENT PRINTER DISCOVERY WARNING]:",
                e
            )

    if not printers:

        printers.append({
            "name": "Microsoft Print to PDF",
            "driver": "Virtual",
            "status": "Normal",
            "is_default": True
        })

    return printers


# ============================================================
# PRINTER SELECTION
# ============================================================

def select_target_printer(
    color_mode: str,
    config: dict,
    installed_printers: list
) -> str:

    printer_names = [
        p["name"]
        for p in installed_printers
        if p.get("name")
    ]

    if not printer_names:
        raise RuntimeError(
            "No Windows printers were detected."
        )

    default_printer = next(
        (
            p["name"]
            for p in installed_printers
            if p.get("is_default")
        ),
        printer_names[0]
    )

    mode = str(color_mode).lower().strip()

    # --------------------------------------------------------
    # COLOR
    # --------------------------------------------------------

    if mode in ("color", "colour"):

        target = config.get(
            "color_printer",
            ""
        ).strip()

        if not target:

            target = next(
                (
                    n
                    for n in printer_names
                    if any(
                        x in n.lower()
                        for x in (
                            "epson",
                            "color",
                            "colour",
                            "l3210"
                        )
                    )
                ),
                ""
            )

    # --------------------------------------------------------
    # BLACK & WHITE
    # --------------------------------------------------------

    else:

        target = config.get(
            "bw_printer",
            ""
        ).strip()

        if not target:

            target = next(
                (
                    n
                    for n in printer_names
                    if any(
                        x in n.lower()
                        for x in (
                            "kyocera",
                            "m2040",
                            "laser",
                            "mono",
                            "black"
                        )
                    )
                ),
                ""
            )

    # --------------------------------------------------------
    # VALIDATE CONFIGURED PRINTER
    # --------------------------------------------------------

    if target and target in printer_names:
        return target

    print(
        f"[AGENT PRINTER WARNING] Configured printer "
        f"'{target}' was not found."
    )

    print(
        f"[AGENT PRINTER FALLBACK] Using default printer: "
        f"{default_printer}"
    )

    return default_printer


# ============================================================
# DOWNLOAD FILE
# ============================================================

def download_file(
    backend_url: str,
    file_rel_path: str
) -> Path:

    filename = Path(file_rel_path).name

    target_path = TEMP_DOWNLOAD_DIR / filename

    full_url = (
        f"{backend_url.rstrip('/')}"
        f"{file_rel_path if file_rel_path.startswith('/') else '/' + file_rel_path}"
    )

    print(
        f"[AGENT DOWNLOAD] {full_url}"
    )

    req = urllib.request.Request(
        full_url,
        headers={
            "User-Agent": "PrintFlowAgent/1.0"
        }
    )

    with urllib.request.urlopen(
        req,
        timeout=30
    ) as response:

        with target_path.open("wb") as out_file:

            shutil.copyfileobj(
                response,
                out_file
            )

    if not target_path.exists():
        raise RuntimeError(
            "Downloaded file does not exist."
        )

    file_size = target_path.stat().st_size

    if file_size <= 0:
        raise RuntimeError(
            "Downloaded file is empty."
        )

    print(
        f"[AGENT FILE SIZE] {file_size} bytes"
    )

    return target_path


# ============================================================
# FIND SUMATRAPDF
# ============================================================

def find_sumatra_pdf():

    candidates = [

        shutil.which("SumatraPDF.exe"),

        shutil.which("SumatraPDF"),

        r"C:\Program Files\SumatraPDF\SumatraPDF.exe",

        r"C:\Program Files (x86)\SumatraPDF\SumatraPDF.exe",

        str(
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "SumatraPDF"
            / "SumatraPDF.exe"
        ),

    ]

    for candidate in candidates:

        if candidate and Path(candidate).exists():

            return candidate

    return None


# ============================================================
# VERIFY WINDOWS PRINTER
# ============================================================

def verify_windows_printer(printer_name: str):

    ps_cmd = (
        f'Get-Printer -Name "{printer_name}" '
        f'-ErrorAction Stop | '
        f'Select-Object -ExpandProperty Name'
    )

    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            ps_cmd
        ],
        capture_output=True,
        text=True,
        timeout=10
    )

    if result.returncode != 0:

        raise RuntimeError(
            f"Printer not found: {printer_name}"
        )

    print(
        f"[AGENT PRINTER VERIFIED] {printer_name}"
    )


# ============================================================
# PRINT DOCUMENT
# ============================================================

def print_document_silently(
    file_path: Path,
    printer_name: str,
    copies: int = 1,
    orientation: str = "portrait"
):

    ext = file_path.suffix.lower()

    print(
        f"[AGENT SILENT PRINT] "
        f"Printing '{file_path.name}' "
        f"({ext}) to '{printer_name}' "
        f"| Copies: {copies} "
        f"| Orient: {orientation}"
    )

    if copies < 1:
        copies = 1

    # --------------------------------------------------------
    # LINUX / MAC
    # --------------------------------------------------------

    if sys.platform != "win32":

        lp = shutil.which("lp")

        if not lp:

            raise RuntimeError(
                "lp printing command not found."
            )

        cmd = [
            lp,
            "-d",
            printer_name,
            "-n",
            str(copies),
            str(file_path)
        ]

        subprocess.run(
            cmd,
            check=True,
            timeout=30
        )

        return True

    # --------------------------------------------------------
    # WINDOWS
    # --------------------------------------------------------

    verify_windows_printer(
        printer_name
    )

    # --------------------------------------------------------
    # PDF
    # --------------------------------------------------------

    if ext == ".pdf":

        sumatra = find_sumatra_pdf()

        if not sumatra:

            raise RuntimeError(
                "SumatraPDF not found. "
                "Install SumatraPDF for reliable silent PDF printing."
            )

        settings = f"{copies}x"

        if orientation.lower() == "landscape":
            settings += ",landscape"
        else:
            settings += ",portrait"

        cmd = [
            sumatra,
            "-silent",
            "-print-to",
            printer_name,
            "-print-settings",
            settings,
            str(file_path)
        ]

        print(
            f"[AGENT PDF ENGINE] {sumatra}"
        )

        print(
            f"[AGENT PDF SETTINGS] {settings}"
        )

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode != 0:

            raise RuntimeError(
                "SumatraPDF printing failed. "
                f"ExitCode={result.returncode} "
                f"STDOUT={result.stdout.strip()} "
                f"STDERR={result.stderr.strip()}"
            )

        print(
            f"[AGENT PDF SPOOL SUBMITTED] "
            f"'{file_path.name}' -> "
            f"'{printer_name}'"
        )

        return True

    # --------------------------------------------------------
    # DOC / DOCX
    # --------------------------------------------------------

    if ext in (".doc", ".docx"):

        word = None
        doc = None

        try:

            import win32com.client

            word = win32com.client.Dispatch(
                "Word.Application"
            )

            word.Visible = False
            word.DisplayAlerts = 0

            doc = word.Documents.Open(
                str(file_path),
                ReadOnly=True
            )

            word.ActivePrinter = printer_name

            doc.PrintOut(
                Copies=copies,
                Background=False
            )

            print(
                f"[AGENT WORD PRINT SUBMITTED] "
                f"'{file_path.name}' -> "
                f"'{printer_name}'"
            )

            return True

        except Exception as word_err:

            raise RuntimeError(
                f"Word printing failed: {word_err}"
            )

        finally:

            try:
                if doc:
                    doc.Close(False)
            except Exception:
                pass

            try:
                if word:
                    word.Quit()
            except Exception:
                pass

    # --------------------------------------------------------
    # IMAGE / TXT
    # --------------------------------------------------------

    try:

        import win32api

        for _ in range(copies):

            result = win32api.ShellExecute(
                0,
                "printto",
                str(file_path),
                f'"{printer_name}"',
                str(file_path.parent),
                0
            )

            if result <= 32:

                raise RuntimeError(
                    f"Windows printto failed with code {result}"
                )

            time.sleep(1)

        print(
            f"[AGENT WINDOWS PRINTTO SUBMITTED] "
            f"'{file_path.name}' -> "
            f"'{printer_name}'"
        )

        return True

    except Exception as win32_err:

        raise RuntimeError(
            f"Windows printto failed: {win32_err}"
        )


# ============================================================
# BACKEND REQUEST HELPER
# ============================================================

def backend_request(
    url: str,
    agent_token: str,
    data=None,
    method="POST"
):

    headers = {
        "X-Print-Agent-Token": agent_token,
        "User-Agent": "PrintFlowAgent/1.0"
    }

    if data is not None:

        encoded_data = json.dumps(data).encode(
            "utf-8"
        )

        headers["Content-Type"] = (
            "application/json"
        )

    else:

        encoded_data = None

    req = urllib.request.Request(
        url,
        data=encoded_data,
        headers=headers,
        method=method
    )

    with urllib.request.urlopen(
        req,
        timeout=15
    ) as response:

        raw = response.read().decode(
            "utf-8"
        )

        if not raw:
            return {}

        return json.loads(raw)


# ============================================================
# RUN AGENT
# ============================================================

def run_agent():

    print("==================================================")
    print("  PrintFlow Local Windows Print Agent v1.1")
    print("==================================================")

    config = load_agent_config()

    backend_url = config.get(
        "backend_url",
        "https://print-flow-mu.vercel.app"
    ).rstrip("/")

    agent_token = (
        os.environ.get("PRINT_AGENT_TOKEN")
        or config.get(
            "agent_token",
            "PF_AGENT_SECRET_TOKEN_2026"
        )
    ).strip()

    poll_interval = int(
        config.get(
            "poll_interval_seconds",
            3
        )
    )

    # --------------------------------------------------------
    # STARTUP CLEANUP
    # --------------------------------------------------------

    if TEMP_DOWNLOAD_DIR.exists():

        for item in TEMP_DOWNLOAD_DIR.glob("*"):

            if item.is_file():

                try:

                    item.unlink()

                    print(
                        f"[AGENT STARTUP CLEANUP] "
                        f"Removed: {item.name}"
                    )

                except Exception:
                    pass

    # --------------------------------------------------------
    # STARTUP INFO
    # --------------------------------------------------------

    print(
        f" Target Backend: {backend_url}"
    )

    print(
        f" Poll Interval : {poll_interval} seconds"
    )

    print(
        f" B&W Printer   : "
        f"{config.get('bw_printer', '')}"
    )

    print(
        f" Color Printer : "
        f"{config.get('color_printer', '')}"
    )

    print(
        " Agent Status   : READY / CONNECTED\n"
    )

    # --------------------------------------------------------
    # MAIN LOOP
    # --------------------------------------------------------

    while True:

        try:

            # ------------------------------------------------
            # DISCOVER PRINTERS
            # ------------------------------------------------

            installed_printers = (
                get_installed_windows_printers()
            )

            # ------------------------------------------------
            # POLL BACKEND
            # ------------------------------------------------

            poll_url = (
                f"{backend_url}/api/agent/poll"
            )

            poll_data = {
                "printers": installed_printers,
                "status": "ONLINE"
            }

            resp_data = backend_request(
                poll_url,
                agent_token,
                poll_data,
                "POST"
            )

            queued_jobs = resp_data.get(
                "jobs",
                []
            )

            if queued_jobs:

                print(
                    f"[AGENT POLL] Found "
                    f"{len(queued_jobs)} pending "
                    f"print job(s) in queue!"
                )

            # ------------------------------------------------
            # PROCESS JOBS
            # ------------------------------------------------

            for job in queued_jobs:

                order_id = job.get(
                    "order_id"
                )

                file_rel_path = job.get(
                    "file_path"
                )

                color_mode = job.get(
                    "color_mode",
                    "black_white"
                )

                copies = int(
                    job.get(
                        "copies",
                        1
                    )
                )

                orientation = job.get(
                    "orientation",
                    "portrait"
                )

                if not order_id:

                    print(
                        "[AGENT JOB ERROR] "
                        "Missing order_id"
                    )

                    continue

                if not file_rel_path:

                    print(
                        f"[AGENT JOB ERROR] "
                        f"Order {order_id} has no file_path"
                    )

                    continue

                # --------------------------------------------
                # SELECT PRINTER
                # --------------------------------------------

                try:

                    target_printer = (
                        select_target_printer(
                            color_mode,
                            config,
                            installed_printers
                        )
                    )

                except Exception as printer_err:

                    print(
                        f"[AGENT PRINTER ERROR] "
                        f"Order {order_id}: "
                        f"{printer_err}"
                    )

                    continue

                print(
                    f"[AGENT ROUTING] "
                    f"Order={order_id} "
                    f"Mode={color_mode} "
                    f"Printer={target_printer}"
                )

                # --------------------------------------------
                # CLAIM JOB
                # --------------------------------------------

                claim_url = (
                    f"{backend_url}"
                    f"/api/agent/claim/"
                    f"{order_id}"
                )

                try:

                    claim_res = backend_request(
                        claim_url,
                        agent_token,
                        None,
                        "POST"
                    )

                    if claim_res.get(
                        "status"
                    ) != "success":

                        print(
                            f"[AGENT CLAIM REJECTED] "
                            f"Order {order_id}"
                        )

                        continue

                except Exception as claim_err:

                    print(
                        f"[AGENT CLAIM ERROR] "
                        f"Order {order_id}: "
                        f"{claim_err}"
                    )

                    continue

                print(
                    f"[AGENT CLAIMED ORDER] "
                    f"Order ID: {order_id} "
                    f"| State: PRINTING"
                )

                local_file = None

                try:

                    # ----------------------------------------
                    # DOWNLOAD
                    # ----------------------------------------

                    local_file = download_file(
                        backend_url,
                        file_rel_path
                    )

                    print(
                        f"[AGENT FILE DOWNLOADED] "
                        f"File: {local_file.name}"
                    )

                    # ----------------------------------------
                    # PRINT
                    # ----------------------------------------

                    print_document_silently(
                        local_file,
                        target_printer,
                        copies,
                        orientation
                    )

                    # ----------------------------------------
                    # PRINT SUCCESS
                    # ----------------------------------------

                    complete_url = (
                        f"{backend_url}"
                        f"/api/agent/complete/"
                        f"{order_id}"
                    )

                    complete_data = {
                        "status": "COMPLETED",
                        "printed_by_printer": target_printer
                    }

                    backend_request(
                        complete_url,
                        agent_token,
                        complete_data,
                        "POST"
                    )

                    print(
                        f"[AGENT JOB COMPLETED] "
                        f"Order {order_id} marked "
                        f"COMPLETED on backend!"
                    )

                except Exception as print_err:

                    # ----------------------------------------
                    # PRINT FAILED
                    # ----------------------------------------

                    print(
                        f"[AGENT PRINT ERROR] "
                        f"Order {order_id}: "
                        f"{print_err}"
                    )

                    fail_url = (
                        f"{backend_url}"
                        f"/api/agent/complete/"
                        f"{order_id}"
                    )

                    fail_data = {
                        "status": "FAILED",
                        "error": str(print_err),
                        "printed_by_printer": target_printer
                    }

                    try:

                        backend_request(
                            fail_url,
                            agent_token,
                            fail_data,
                            "POST"
                        )

                        print(
                            f"[AGENT BACKEND] "
                            f"Order {order_id} marked FAILED"
                        )

                    except Exception as backend_err:

                        print(
                            f"[AGENT BACKEND ERROR] "
                            f"{backend_err}"
                        )

                finally:

                    # ----------------------------------------
                    # LOCAL PRIVACY CLEANUP
                    # ----------------------------------------

                    if (
                        local_file
                        and local_file.exists()
                        and local_file.is_file()
                    ):

                        try:

                            time.sleep(2.5)

                            local_file.unlink()

                            print(
                                f"[AGENT LOCAL PRIVACY CLEANUP] "
                                f"Local temp file "
                                f"'{local_file.name}' deleted."
                            )

                        except Exception as cleanup_err:

                            print(
                                f"[AGENT LOCAL CLEANUP ERROR] "
                                f"{cleanup_err}"
                            )

        except Exception as poll_err:

            print(
                "\n========== POLL ERROR =========="
            )

            print(
                type(poll_err).__name__
            )

            print(
                repr(poll_err)
            )

            print(
                "================================\n"
            )

        time.sleep(
            poll_interval
        )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    run_agent()
