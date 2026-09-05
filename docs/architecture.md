# PrintFlow — System Architecture & Implementation

## 1. System Overview Architecture

```
                                  +---------------------------------------+
                                  |            FRONTEND WEB APP           |
                                  |  HTML5 / Modern CSS / Vanilla JS      |
                                  |  (Mobile Responsive / User Session)   |
                                  +-------------------+-------------------+
                                                      |
                                          HTTP / REST | JSON
                                                      v
                                  +-------------------+-------------------+
                                  |         VERCEL / FASTAPI BACKEND      |
                                  |  main.py / api/*.py / storage.py      |
                                  +---------+-------------------+---------+
                                            |                   |
                     HMAC SHA-256 Signature |                   | Durable Storage
                                Validation |                   v (PostgreSQL / SQLite)
                                            v         +---------+---------+
                                  +---------+-------+ |  printflow_orders |
                                  | Razorpay Gateway| +-------------------+
                                  +-----------------+
                                            |
                                            | PRINT_QUEUED Jobs
                                            v (Polled via REST)
                                  +---------------------------------------+
                                  |      LOCAL WINDOWS PRINT AGENT        |
                                  |  print_agent.py / print_dispatcher.py |
                                  +-------------------+-------------------+
                                                      |
                                      SumatraPDF CLI  | Native Windows Spooler
                                      (-print-settings "fit,duplexlong...")
                                                      v
                                  +---------------------------------------+
                                  |        PHYSICAL HARDWARE PRINTER      |
                                  |  (Kyocera ECOSYS M2040dn KX / USB/Wi-Fi)|
                                  +-------------------+-------------------+
                                                      |
                                     Agent Status:    | Status: COMPLETED
                                     PRINTED          v
                                  +-------------------+-------------------+
                                  |    2.5s SECURE DISK CLEANUP WORKER    |
                                  |  Schedule unlink of /uploads/file.pdf |
                                  +---------------------------------------+
```

---

## 2. Comprehensive Execution Flow

1. **Frontend Authentication & File Selection**:
   - User authenticates via mobile phone + OTP on `login.html`. Session stored in `localStorage`.
   - File is uploaded to `/api/upload-pdf`. Backend saves document to `UPLOAD_DIR` (`/uploads/uuid_file.pdf`) and returns document URI & page count.
2. **Print Configuration & Live Preview**:
   - User configures settings on `print-details.html` (B&W/Colour, Single/Double, A4/Letter/Legal, Portrait/Landscape, Fit/Actual, Margins, Copies, Standard/Micro Xerox N-up).
   - `script.js` renders real-time visual preview on canvas.
3. **Canonical Price Calculation**:
   - Client calculates price for UI display based on rules: B&W Single ₹2, B&W Double ₹1, Colour Single ₹6, Micro Xerox ₹3/sheet.
   - Backend independently re-calculates price server-side in `/api/create-razorpay-order` to prevent DevTools tampering.
4. **Order Creation & Razorpay Gateway**:
   - `/api/create-razorpay-order` issues a Razorpay Order ID (`rzp_live_*` or mock) and persists order record in `storage.py` with status `Pending`.
   - Razorpay Checkout modal launches in frontend.
5. **Server-Side Verification & Queue Transition**:
   - Client sends `razorpay_order_id`, `razorpay_payment_id`, and `razorpay_signature` to `/api/verify-payment`.
   - Backend computes expected HMAC SHA-256 digest using `RAZORPAY_KEY_SECRET`. Upon match, status updates to `PRINT_QUEUED`.
6. **Print Agent Discovery & Polling**:
   - Windows desktop daemon (`print_agent.py`) discovers local Windows printers via `printer_manager.py` (using `win32print` / `wmi` / PowerShell).
   - Agent periodically polls `/api/agent/poll` sending `X-Print-Agent-Token` header and printer telemetry.
7. **Atomic Claim & Hardware Spooling**:
   - Agent fetches `PRINT_QUEUED` orders and claims target job via POST `/api/agent/claim/{order_id}` (returns HTTP 409 if claimed concurrently).
   - Agent downloads file from `/uploads/{filename}`.
   - If `print_mode` is `micro_xerox` with `pages_per_sheet` > 1, `print_dispatcher.py` invokes `create_n_up_pdf` using `pypdf` to synthesize an N-up layout PDF.
   - `print_dispatcher.py` constructs SumatraPDF CLI command string:
     ```bash
     SumatraPDF.exe -print-to "Kyocera ECOSYS M2040dn KX" -print-settings "fit,duplexlong,paper=a4,portrait,monochrome" -exit-when-done "C:\temp\job.pdf"
     ```
   - Notice: `fit` flag is explicitly passed to ensure full-page scaling without cropping; `duplexlong` triggers hardware double-sided printing.
8. **Completion & Automated Privacy Cleanup**:
   - Agent reports completion via POST `/api/agent/complete/{order_id}` with status `COMPLETED`.
   - Backend marks `document_status` = `PRINTED` and immediately launches async thread `schedule_secure_document_cleanup(order_id, 2.5)`.
   - 2.5 seconds later, the worker permanently unlinks `/uploads/uuid_file.pdf` from disk and sets `document_status` = `DELETED`.
9. **Receipt Success UI**:
   - Frontend polling `/api/orders/{order_id}/status` receives `status` = `COMPLETED` and `document_status` = `DELETED`.
   - Metallic hood receipt component in `success.html` animates downward roll displaying exact order details and privacy confirmation badge.

---

## 3. Directory & File Structure

```
/
├── main.py                     # Primary FastAPI application entrypoint & API handlers
├── storage.py                  # Database abstraction layer (PostgreSQL / SQLite3)
├── print_agent.py              # Local Windows Print Agent daemon & polling worker
├── print_dispatcher.py         # Hardware print execution engine & pypdf N-up generator
├── printer_manager.py          # Windows printer discovery & printer availability inspector
├── vercel.json                 # Vercel deployment rewrite rules & serverless routing
├── index.html                  # Root landing page redirect
├── login.html / login.js       # OTP login page & session initialization logic
├── home.html                   # Dashboard file upload page
├── print-details.html          # Extended print configuration form & Live Preview canvas
├── payment.html                # Payment initiation view
├── success.html                # Animated metallic hood receipt printer completion UI
├── admin.html                  # Administrator monitoring & retry dashboard
├── script.js                   # Unified frontend state manager & pricing engine
├── style.css                   # Custom PrintFlow design system CSS stylesheet
├── requirements.txt            # Python dependencies (fastapi, uvicorn, pypdf, requests, etc.)
├── api/                        # Direct Vercel Serverless Function entrypoints
│   ├── create-order.py
│   ├── create-razorpay-order.py
│   ├── verify-payment.py
│   ├── verify-razorpay-payment.py
│   ├── upload-pdf.py
│   ├── agent/
│   │   ├── poll.py
│   │   ├── claim.py
│   │   └── complete.py
│   └── orders/
│       └── status.py
└── docs/                       # Project documentation suite
    ├── PRD.md
    ├── architecture.md
    ├── rules.md
    ├── design.md
    ├── phases.md
    └── memory.md
```

---

## 4. Primary API Endpoint Reference

| HTTP Method | Path | Description | Access / Auth |
|---|---|---|---|
| `GET` | `/health` | Server health check endpoint | Public |
| `POST` | `/upload-pdf` | Upload printable document file | Authenticated Session |
| `POST` | `/api/create-razorpay-order` | Server-side Razorpay order generation & price validation | Authenticated Session |
| `POST` | `/api/verify-payment` | Validate HMAC SHA-256 payment signature & queue job | Public / Razorpay Callback |
| `POST` | `/api/agent/poll` | Fetch `PRINT_QUEUED` jobs & report discovered printers | `PRINT_AGENT_TOKEN` |
| `POST` | `/api/agent/claim/{order_id}` | Atomically claim job for printing (HTTP 409 on conflict) | `PRINT_AGENT_TOKEN` |
| `POST` | `/api/agent/complete/{order_id}` | Report job status (`COMPLETED`/`FAILED`) & trigger 2.5s file cleanup | `PRINT_AGENT_TOKEN` |
| `GET` | `/api/orders/{order_id}/status` | Order status & document cleanup polling | Public / Customer |
| `POST` | `/api/orders/{order_id}/retry` | Re-queue failed or cancelled order for printing | Customer / Admin |
| `GET` | `/api/agent/status` | Agent connectivity state & discovered physical printers | Admin / Customer |

---

## 5. Storage Layer Schema (`storage.py`)

Table: `printflow_orders`

| Column | Type | Description |
|---|---|---|
| `order_id` | `TEXT PRIMARY KEY` | Unique PrintFlow Order Identifier |
| `razorpay_order_id` | `TEXT` | Razorpay Order ID |
| `razorpay_payment_id` | `TEXT` | Razorpay Payment ID |
| `file_name` | `TEXT NOT NULL` | Original uploaded filename |
| `file_path` | `TEXT` | Relative path to server file (cleared upon deletion) |
| `pages` | `INTEGER` | Document page count |
| `copies` | `INTEGER` | Print copies count |
| `color_mode` | `TEXT` | `black_white` or `color` |
| `duplex` | `TEXT` | `single` or `double` |
| `paper_size` | `TEXT` | `a4`, `letter`, `legal` |
| `orientation` | `TEXT` | `portrait` or `landscape` |
| `scale_mode` | `TEXT` | `fit` or `actual` |
| `margins` | `TEXT` | `normal`, `minimum`, `none` |
| `print_mode` | `TEXT` | `standard` or `micro_xerox` |
| `pages_per_sheet` | `INTEGER` | Grid density (1, 2, 4, 6, 9, 16) |
| `page_order` | `TEXT` | `horizontal` or `vertical` |
| `customer_mobile` | `TEXT` | Customer mobile number |
| `amount` | `REAL / DOUBLE` | Total canonical order price in INR |
| `paid` | `BOOLEAN` | Payment status |
| `status` | `TEXT` | `Pending`, `PRINT_QUEUED`, `PRINTING`, `COMPLETED`, `FAILED` |
| `document_status` | `TEXT` | `UPLOADED`, `PRINTING`, `PRINTED`, `DELETING`, `DELETED` |
| `timestamp` | `TEXT` | ISO Creation Timestamp |

---

## 6. Vercel Serverless Architecture

- In Vercel environments, `vercel.json` rewrites all `/api/*` and static routes to `main.py` WSGI/ASGI handlers or dedicated standalone Vercel Serverless python endpoints in `api/`.
- Persistent storage utilizes PostgreSQL when `DATABASE_URL` is set, with an automated fallback to SQLite3 for local execution (`orders/printflow.sqlite3`).
- Temporary upload buffer uses `/tmp/printflow-uploads` on Vercel and local `./uploads/` during desktop execution.
