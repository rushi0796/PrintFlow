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
# DEFAULT CONFIG
# ============================================================

DEFAULT_CONFIG = {
    "backend_url": "https://print-flow-mu.vercel.app",
    "agent_token": "PF_AGENT_SECRET_TOKEN_2026",
    "poll_interval_seconds": 3,
    "bw_printer": "Kyocera ECOSYS M2040dn KX",
    "color_printer": "EPSON L3210 Series",
    "auto_routing": True
}


# ============================================================
# CONFIG
# ============================================================

def load_agent_config():
    if not CONFIG_FILE.exists():

        if EXAMPLE_CONFIG_FILE.exists():
            shutil.copy(EXAMPLE_CONFIG_FILE, CONFIG_FILE)

        else:
            CONFIG_FILE.write_text(
                json.dumps(DEFAULT_CONFIG, indent=2),
                encoding="utf-8"
            )

    try:
        config = json.loads(
            CONFIG_FILE.read_text(encoding="utf-8")
        )

        if not isinstance(config, dict):
            raise ValueError("Agent config must be a JSON object.")

        # Fill missing values without destroying existing config
        for key, value in DEFAULT_CONFIG.items():
            config.setdefault(key, value)

        return config

    except Exception as err:

        print("[AGENT CONFIG ERROR]", repr(err))

        return DEFAULT_CONFIG.copy()


# ============================================================
# WINDOWS PRINTER DISCOVERY
# ============================================================

def get_installed_windows_printers():

    printers = []

    if sys.platform != "win32":
        return printers

    try:

        ps_cmd = (
            "Get-Printer | "
            "Select-Object Name,DriverName,PrinterStatus,IsDefault | "
            "ConvertTo-Json -Compress"
        )

        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps_cmd
            ],
            capture_output=True,
            text=True,
            timeout=15
        )

        if result.returncode != 0:

            print(
                "[AGENT PRINTER DISCOVERY ERROR]",
                result.stderr.strip()
            )

            return printers

        raw = result.stdout.strip()

        if not raw:
            return printers

        data = json.loads(raw)

        if isinstance(data, dict):
            data = [data]

        for printer in data:

            name = str(
                printer.get("Name", "")
            ).strip()

            if not name:
                continue

            printers.append({
                "name": name,
                "driver": str(
                    printer.get("DriverName", "")
                ),
                "status": str(
                    printer.get("PrinterStatus", "Unknown")
                ),
                "is_default": bool(
                    printer.get("IsDefault", False)
                )
            })

    except Exception as err:

        print(
            "[AGENT PRINTER DISCOVERY WARNING]",
            repr(err)
        )

    return printers


# ============================================================
# VERIFY PRINTER
# ============================================================

def verify_windows_printer(printer_name):

    if sys.platform != "win32":
        return True

    ps_script = """
$printer = Get-Printer -Name %s -ErrorAction SilentlyContinue

if ($null -eq $printer) {
    exit 1
}

Write-Output $printer.Name
""" % json.dumps(printer_name)

    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            ps_script
        ],
        capture_output=True,
        text=True,
        timeout=10
    )

    if result.returncode != 0:

        raise RuntimeError(
            f"Windows printer not found: {printer_name}"
        )

    actual_name = result.stdout.strip()

    if actual_name.lower() != printer_name.lower():

        raise RuntimeError(
            f"Printer verification failed. "
            f"Requested='{printer_name}', "
            f"Found='{actual_name}'"
        )

    print(
        f"[AGENT PRINTER VERIFIED] {actual_name}"
    )

    return True


# ============================================================
# PRINTER SELECTION
# ============================================================

def select_target_printer(
    color_mode,
    config,
    installed_printers
):

    printer_names = [
        p["name"]
        for p in installed_printers
        if p.get("name")
    ]

    if not printer_names:

        raise RuntimeError(
            "No Windows printers detected."
        )

    mode = str(
        color_mode or "black_white"
    ).lower().strip()

    # --------------------------------------------------------
    # COLOR
    # --------------------------------------------------------

    if mode in (
        "color",
        "colour",
        "full_color",
        "full-colour"
    ):

        configured = str(
            config.get("color_printer", "")
        ).strip()

        if configured:
            if configured in printer_names:
                return configured

            print(
                f"[AGENT COLOR WARNING] "
                f"Configured color printer "
                f"'{configured}' not found."
            )

        # Automatic color detection
        for printer in printer_names:

            name = printer.lower()

            if any(
                keyword in name
                for keyword in (
                    "epson",
                    "color",
                    "colour",
                    "l3210"
                )
            ):
                return printer

    # --------------------------------------------------------
    # BLACK & WHITE
    # --------------------------------------------------------

    configured = str(
        config.get("bw_printer", "")
    ).strip()

    if configured:

        if configured in printer_names:
            return configured

        print(
            f"[AGENT B&W WARNING] "
            f"Configured B&W printer "
            f"'{configured}' not found."
        )

    # Automatic Kyocera detection
    for printer in printer_names:

        name = printer.lower()

        if any(
            keyword in name
            for keyword in (
                "kyocera",
                "m2040",
                "m2640",
                "laser",
                "mono"
            )
        ):

            return printer

    # --------------------------------------------------------
    # DEFAULT PRINTER
    # --------------------------------------------------------

    default_printer = next(
        (
            p["name"]
            for p in installed_printers
            if p.get("is_default")
        ),
        None
    )

    if default_printer:
        print(
            f"[AGENT PRINTER FALLBACK] "
            f"Using Windows default printer: "
            f"{default_printer}"
        )

        return default_printer

    return printer_names[0]


# ============================================================
# DOWNLOAD FILE
# ============================================================

def download_file(
    backend_url,
    file_rel_path
):

    if not file_rel_path:
        raise RuntimeError(
            "Order does not contain file_path."
        )

    filename = Path(
        file_rel_path
    ).name

    if not filename:
        raise RuntimeError(
            "Invalid filename."
        )

    target_path = (
        TEMP_DOWNLOAD_DIR / filename
    )

    full_url = (
        backend_url.rstrip("/")
        + (
            file_rel_path
            if file_rel_path.startswith("/")
            else "/" + file_rel_path
        )
    )

    print(
        f"[AGENT DOWNLOAD] {full_url}"
    )

    request = urllib.request.Request(
        full_url,
        headers={
            "User-Agent": "PrintFlowAgent/2.0"
        }
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=60
        ) as response:

            status = getattr(
                response,
                "status",
                200
            )

            if status >= 400:
                raise RuntimeError(
                    f"File download HTTP {status}"
                )

            with target_path.open(
                "wb"
            ) as output:

                shutil.copyfileobj(
                    response,
                    output
                )

    except Exception as err:

        raise RuntimeError(
            f"Could not download file: {err}"
        )

    if not target_path.exists():

        raise RuntimeError(
            "Downloaded file does not exist."
        )

    size = target_path.stat().st_size

    if size <= 0:

        raise RuntimeError(
            "Downloaded file is empty."
        )

    print(
        f"[AGENT FILE DOWNLOADED] "
        f"{target_path.name} "
        f"({size} bytes)"
    )

    return target_path


# ============================================================
# FIND SUMATRA PDF
# ============================================================

def find_sumatra_pdf():

    candidates = []

    # PATH
    candidates.append(
        shutil.which("SumatraPDF.exe")
    )

    candidates.append(
        shutil.which("SumatraPDF")
    )

    # Program Files
    program_files = os.environ.get(
        "PROGRAMFILES",
        r"C:\Program Files"
    )

    program_files_x86 = os.environ.get(
        "PROGRAMFILES(X86)",
        r"C:\Program Files (x86)"
    )

    local_app_data = os.environ.get(
        "LOCALAPPDATA",
        ""
    )

    user_profile = os.environ.get(
        "USERPROFILE",
        ""
    )

    candidates.extend([
        os.path.join(
            program_files,
            "SumatraPDF",
            "SumatraPDF.exe"
        ),

        os.path.join(
            program_files_x86,
            "SumatraPDF",
            "SumatraPDF.exe"
        ),

        os.path.join(
            local_app_data,
            "SumatraPDF",
            "SumatraPDF.exe"
        ),

        os.path.join(
            user_profile,
            "Downloads",
            "SumatraPDF.exe"
        ),

        os.path.join(
            user_profile,
            "Desktop",
            "SumatraPDF.exe"
        ),

        str(
            BASE_DIR / "SumatraPDF.exe"
        )
    ])

    checked = set()

    for candidate in candidates:

        if not candidate:
            continue

        candidate = os.path.abspath(candidate)

        if candidate in checked:
            continue

        checked.add(candidate)

        if os.path.isfile(candidate):

            print(
                f"[AGENT PDF ENGINE FOUND] "
                f"{candidate}"
            )

            return candidate

    return None


# ============================================================
# GET PRINTER STATUS
# ============================================================

def get_printer_status(
    printer_name
):

    if sys.platform != "win32":
        return "UNKNOWN"

    ps_script = """
$p = Get-Printer -Name %s -ErrorAction SilentlyContinue

if ($null -eq $p) {
    Write-Output "NOT_FOUND"
} else {
    Write-Output $p.PrinterStatus
}
""" % json.dumps(printer_name)

    try:

        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps_script
            ],
            capture_output=True,
            text=True,
            timeout=10
        )

        return (
            result.stdout.strip()
            or "UNKNOWN"
        )

    except Exception:

        return "UNKNOWN"


# ============================================================
# PDF PRINT
# ============================================================

def print_pdf(
    file_path,
    printer_name,
    copies,
    orientation,
    color_mode,
    duplex
):

    sumatra = find_sumatra_pdf()

    if not sumatra:

        raise RuntimeError(
            "SumatraPDF was not found. "
            "Install SumatraPDF before using PrintFlow "
            "for silent PDF printing."
        )

    settings = [
        f"{copies}x"
    ]

    # Orientation
    if str(
        orientation
    ).lower() == "landscape":

        settings.append(
            "landscape"
        )

    else:

        settings.append(
            "portrait"
        )

    # Color
    mode = str(
        color_mode or "black_white"
    ).lower()

    if mode in (
        "color",
        "colour",
        "full_color",
        "full-colour"
    ):

        settings.append(
            "color"
        )

    else:

        settings.append(
            "monochrome"
        )

    # Duplex
    duplex_mode = str(
        duplex or "single"
    ).lower()

    if duplex_mode in (
        "double",
        "duplex",
        "two_sided",
        "two-sided",
        "twosided",
        "long_edge"
    ):

        settings.append(
            "duplexlong"
        )

    elif duplex_mode in (
        "short_edge",
        "duplex_short"
    ):

        settings.append(
            "duplexshort"
        )

    print_settings = ",".join(
        settings
    )

    command = [
        sumatra,
        "-silent",
        "-print-to",
        printer_name,
        "-print-settings",
        print_settings,
        str(file_path)
    ]

    print(
        "[AGENT PDF PRINT]"
    )

    print(
        f"  Engine      : {sumatra}"
    )

    print(
        f"  Printer     : {printer_name}"
    )

    print(
        f"  Settings    : {print_settings}"
    )

    print(
        f"  File        : {file_path.name}"
    )

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=60
    )

    if result.returncode != 0:

        raise RuntimeError(
            "SumatraPDF print failed. "
            f"ExitCode={result.returncode}; "
            f"STDOUT={result.stdout.strip()}; "
            f"STDERR={result.stderr.strip()}"
        )

    print(
        "[AGENT PDF PRINT SUBMITTED]"
    )

    # Give Windows spooler time to receive job
    time.sleep(3)

    return True


# ============================================================
# DOC / DOCX PRINT
# ============================================================

def print_word_document(
    file_path,
    printer_name,
    copies
):

    word = None
    document = None

    try:

        import win32com.client

        print(
            "[AGENT WORD] Starting Microsoft Word..."
        )

        word = win32com.client.Dispatch(
            "Word.Application"
        )

        word.Visible = False
        word.DisplayAlerts = 0

        document = word.Documents.Open(
            str(file_path),
            ReadOnly=True
        )

        word.ActivePrinter = printer_name

        document.PrintOut(
            Copies=copies,
            Background=False
        )

        print(
            "[AGENT WORD PRINT SUBMITTED]"
        )

        time.sleep(3)

        return True

    except Exception as err:

        raise RuntimeError(
            f"Word printing failed: {err}"
        )

    finally:

        try:

            if document:
                document.Close(False)

        except Exception:
            pass

        try:

            if word:
                word.Quit()

        except Exception:
            pass


# ============================================================
# IMAGE / TXT PRINT
# ============================================================

def print_windows_shell(
    file_path,
    printer_name,
    copies
):

    try:

        import win32api

    except ImportError:

        raise RuntimeError(
            "pywin32 is not installed. "
            "Run: pip install pywin32"
        )

    for copy_number in range(
        copies
    ):

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
                f"Windows printto failed. "
                f"Error code: {result}"
            )

        print(
            f"[AGENT SHELL PRINT] "
            f"Copy {copy_number + 1}/{copies} submitted"
        )

        time.sleep(2)

    return True


# ============================================================
# MAIN PRINT FUNCTION
# ============================================================

def print_document_silently(
    file_path,
    printer_name,
    copies=1,
    orientation="portrait",
    color_mode="black_white",
    duplex="single"
):

    if not file_path.exists():

        raise RuntimeError(
            f"Print file does not exist: {file_path}"
        )

    copies = max(
        1,
        int(copies)
    )

    verify_windows_printer(
        printer_name
    )

    printer_status = get_printer_status(
        printer_name
    )

    print(
        f"[AGENT PRINTER STATUS] "
        f"{printer_name} = {printer_status}"
    )

    extension = (
        file_path.suffix.lower()
    )

    print("")
    print("==========================================")
    print("          PRINTFLOW PRINT JOB")
    print("==========================================")
    print(f"File        : {file_path.name}")
    print(f"Extension   : {extension}")
    print(f"Printer     : {printer_name}")
    print(f"Copies      : {copies}")
    print(f"Color Mode  : {color_mode}")
    print(f"Duplex      : {duplex}")
    print(f"Orientation : {orientation}")
    print("==========================================")

    # --------------------------------------------------------
    # PDF
    # --------------------------------------------------------

    if extension == ".pdf":

        return print_pdf(
            file_path,
            printer_name,
            copies,
            orientation,
            color_mode,
            duplex
        )

    # --------------------------------------------------------
    # DOC / DOCX
    # --------------------------------------------------------

    if extension in (
        ".doc",
        ".docx"
    ):

        return print_word_document(
            file_path,
            printer_name,
            copies
        )

    # --------------------------------------------------------
    # IMAGE / TXT
    # --------------------------------------------------------

    if extension in (
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".txt"
    ):

        return print_windows_shell(
            file_path,
            printer_name,
            copies
        )

    raise RuntimeError(
        f"Unsupported print format: {extension}"
    )


# ============================================================
# BACKEND REQUEST
# ============================================================

def backend_request(
    url,
    agent_token,
    data=None,
    method="POST"
):

    headers = {
        "X-Print-Agent-Token": agent_token,
        "User-Agent": "PrintFlowAgent/2.0"
    }

    encoded_data = None

    if data is not None:

        encoded_data = json.dumps(
            data
        ).encode("utf-8")

        headers["Content-Type"] = (
            "application/json"
        )

    request = urllib.request.Request(
        url,
        data=encoded_data,
        headers=headers,
        method=method
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=20
        ) as response:

            raw = response.read().decode(
                "utf-8"
            )

            if not raw:
                return {}

            return json.loads(raw)

    except Exception as err:

        raise RuntimeError(
            f"Backend request failed "
            f"{method} {url}: {err}"
        )


# ============================================================
# COMPLETE ORDER
# ============================================================

def complete_order(
    backend_url,
    agent_token,
    order_id,
    printer_name
):

    url = (
        f"{backend_url}"
        f"/api/agent/complete/"
        f"{order_id}"
    )

    data = {
        "status": "COMPLETED",
        "printed_by_printer": printer_name
    }

    return backend_request(
        url,
        agent_token,
        data,
        "POST"
    )


# ============================================================
# FAIL ORDER
# ============================================================

def fail_order(
    backend_url,
    agent_token,
    order_id,
    printer_name,
    error
):

    url = (
        f"{backend_url}"
        f"/api/agent/complete/"
        f"{order_id}"
    )

    data = {
        "status": "FAILED",
        "error": str(error),
        "printed_by_printer": printer_name
    }

    try:

        return backend_request(
            url,
            agent_token,
            data,
            "POST"
        )

    except Exception as backend_error:

        print(
            "[AGENT FAILURE REPORT ERROR]",
            repr(backend_error)
        )

        return None


# ============================================================
# RUN AGENT
# ============================================================

def run_agent():

    print("")
    print("==================================================")
    print("   PrintFlow Local Windows Print Agent v2.0")
    print("==================================================")
    print("")

    config = load_agent_config()

    backend_url = str(
        config.get(
            "backend_url",
            DEFAULT_CONFIG["backend_url"]
        )
    ).rstrip("/")

    agent_token = (
        os.environ.get(
            "PRINT_AGENT_TOKEN"
        )
        or config.get(
            "agent_token",
            DEFAULT_CONFIG["agent_token"]
        )
    ).strip()

    poll_interval = max(
        1,
        int(
            config.get(
                "poll_interval_seconds",
                3
            )
        )
    )

    print(
        f"[CONFIG] Backend      : {backend_url}"
    )

    print(
        f"[CONFIG] Poll interval: {poll_interval}s"
    )

    print(
        f"[CONFIG] B&W printer  : "
        f"{config.get('bw_printer', '')}"
    )

    print(
        f"[CONFIG] Color printer: "
        f"{config.get('color_printer', '')}"
    )

    # --------------------------------------------------------
    # PRINTER CHECK
    # --------------------------------------------------------

    printers = get_installed_windows_printers()

    print("")
    print(
        f"[AGENT] Detected {len(printers)} printer(s):"
    )

    for printer in printers:

        print(
            f"  - {printer['name']} "
            f"| Driver: {printer['driver']} "
            f"| Default: {printer['is_default']}"
        )

    bw_printer = config.get(
        "bw_printer",
        ""
    ).strip()

    if bw_printer:

        if any(
            p["name"] == bw_printer
            for p in printers
        ):

            print(
                f"[AGENT] Kyocera/B&W printer OK: "
                f"{bw_printer}"
            )

        else:

            print(
                f"[AGENT WARNING] "
                f"Configured B&W printer not detected: "
                f"{bw_printer}"
            )

    print("")
    print(
        "[AGENT STATUS] READY / CONNECTED"
    )
    print(
        "[AGENT STATUS] Waiting for print orders..."
    )
    print("")

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
            # POLL
            # ------------------------------------------------

            poll_url = (
                f"{backend_url}/api/agent/poll"
            )

            poll_data = {
                "printers": installed_printers,
                "status": "ONLINE"
            }

            response = backend_request(
                poll_url,
                agent_token,
                poll_data,
                "POST"
            )

            queued_jobs = response.get(
                "jobs",
                []
            )

            if queued_jobs:

                print(
                    f"\n[AGENT POLL] "
                    f"Found {len(queued_jobs)} "
                    f"pending print job(s)!"
                )

            # ------------------------------------------------
            # PROCESS EACH JOB
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

                duplex = job.get(
                    "duplex",
                    "single"
                )

                # ------------------------------------------------
                # VALIDATE JOB
                # ------------------------------------------------

                if not order_id:

                    print(
                        "[AGENT JOB ERROR] "
                        "Missing order_id."
                    )

                    continue

                if not file_rel_path:

                    print(
                        f"[AGENT JOB ERROR] "
                        f"Order {order_id} has no file_path."
                    )

                    continue

                # ------------------------------------------------
                # SELECT PRINTER
                # ------------------------------------------------

                try:

                    target_printer = (
                        select_target_printer(
                            color_mode,
                            config,
                            installed_printers
                        )
                    )

                except Exception as printer_error:

                    print(
                        f"[AGENT PRINTER ERROR] "
                        f"Order {order_id}: "
                        f"{printer_error}"
                    )

                    continue

                print("")
                print(
                    "------------------------------------------"
                )
                print(
                    f"[AGENT JOB] {order_id}"
                )
                print(
                    f"[AGENT MODE] {color_mode}"
                )
                print(
                    f"[AGENT PRINTER] {target_printer}"
                )

                # ------------------------------------------------
                # CLAIM
                # ------------------------------------------------

                claim_url = (
                    f"{backend_url}"
                    f"/api/agent/claim/"
                    f"{order_id}"
                )

                try:

                    claim_response = backend_request(
                        claim_url,
                        agent_token,
                        None,
                        "POST"
                    )

                    if claim_response.get(
                        "status"
                    ) != "success":

                        print(
                            f"[AGENT CLAIM REJECTED] "
                            f"{order_id}"
                        )

                        continue

                except Exception as claim_error:

                    print(
                        f"[AGENT CLAIM ERROR] "
                        f"{order_id}: "
                        f"{claim_error}"
                    )

                    continue

                print(
                    f"[AGENT CLAIMED ORDER] "
                    f"{order_id} | PRINTING"
                )

                local_file = None

                # ------------------------------------------------
                # DOWNLOAD + PRINT
                # ------------------------------------------------

                try:

                    local_file = download_file(
                        backend_url,
                        file_rel_path
                    )

                    # ------------------------------------------------
                    # PRINT
                    # ------------------------------------------------

                    print_document_silently(
                        local_file,
                        target_printer,
                        copies,
                        orientation,
                        color_mode,
                        duplex
                    )

                    # ------------------------------------------------
                    # SUCCESS
                    # ------------------------------------------------

                    complete_order(
                        backend_url,
                        agent_token,
                        order_id,
                        target_printer
                    )

                    print(
                        f"[AGENT JOB COMPLETED] "
                        f"{order_id}"
                    )

                except Exception as print_error:

                    # ------------------------------------------------
                    # FAILURE
                    # ------------------------------------------------

                    print("")
                    print(
                        "========== PRINT FAILED =========="
                    )

                    print(
                        f"Order   : {order_id}"
                    )

                    print(
                        f"Printer : {target_printer}"
                    )

                    print(
                        f"Error   : {print_error}"
                    )

                    print(
                        "=================================="
                    )

                    fail_order(
                        backend_url,
                        agent_token,
                        order_id,
                        target_printer,
                        print_error
                    )

                finally:

                    # ------------------------------------------------
                    # LOCAL FILE CLEANUP
                    # ------------------------------------------------

                    if (
                        local_file
                        and local_file.exists()
                        and local_file.is_file()
                    ):

                        try:

                            # Allow spooler/application to finish
                            time.sleep(3)

                            local_file.unlink()

                            print(
                                f"[AGENT LOCAL PRIVACY CLEANUP] "
                                f"Deleted {local_file.name}"
                            )

                        except Exception as cleanup_error:

                            print(
                                f"[AGENT CLEANUP WARNING] "
                                f"{cleanup_error}"
                            )

            # ------------------------------------------------
            # WAIT
            # ------------------------------------------------

            time.sleep(
                poll_interval
            )

        except KeyboardInterrupt:

            print("")
            print(
                "[AGENT] Stopped by user."
            )
            break

        except Exception as poll_error:

            print("")
            print(
                "========== POLL ERROR =========="
            )

            print(
                f"Type : {type(poll_error).__name__}"
            )

            print(
                f"Error: {poll_error}"
            )

            print(
                "================================"
            )

            time.sleep(
                poll_interval
            )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    run_agent()
