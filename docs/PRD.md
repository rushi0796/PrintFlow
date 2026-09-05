# PrintFlow — Product Requirements Document (PRD)

## 1. What PrintFlow Is
**PrintFlow** is an automated, web-to-physical print fulfillment platform. It allows users to upload documents (PDF, PNG, JPG, WEBP, DOC, DOCX, TXT) via a clean web UI, select detailed print parameters (side, color, paper size, orientation, scaling, margins, copies, or Micro Xerox N-up mode), pay seamlessly via Razorpay, and have their documents automatically dispatched to a physical local printer connected to a dedicated Windows Print Agent bridge.

---

## 2. What We Are Building
We are building a production-ready, security-hardened print execution pipeline consisting of:
1. **Frontend Web Application**: Mobile-first responsive UI supporting mobile login, document upload, live print configuration preview, pricing calculation, Razorpay checkout, and an animated receipt completion page.
2. **Backend API Service**: FastAPI / Vercel Serverless service handling order validation, canonical price calculation, Razorpay signature verification, print queue state management, secure document serving, and automated 2.5-second file deletion.
3. **Local Windows Print Agent**: Python desktop background service (`print_agent.py`, `printer_manager.py`, `print_dispatcher.py`) running on the physical printing host PC. It discovers local printers, polls the PrintFlow backend, claims jobs atomically, synthesizes N-up layouts if required, dispatches jobs to SumatraPDF with exact hardware parameters (`fit`, `duplexlong`/`noduplex`, etc.), and reports completion back to the backend.

---

## 3. Target Users
- **College / University Students**: Students needing quick, affordable document or Micro Xerox printing.
- **Office / Shop Customers**: Users requiring instant B&W or Colour prints without manual shopkeeper intervention.
- **Self-Service Kiosk Users**: Individuals using designated PC terminals for automated printing.

---

## 4. Core User Journey
1. **Authentication**: Mobile number entry & OTP verification (clean cross-user session isolation).
2. **Document Upload**: Drag-and-drop or file picker for supported formats (PDF, images, office documents).
3. **Print Configuration**: Select Standard vs Micro Xerox mode, B&W vs Colour, Single vs Double-sided, Paper Size, Orientation, Scaling, Margins, and Copies.
4. **Live Print Preview**: Real-time visual representation of document layout, duplex flipping, or N-up sheet grids.
5. **Canonical Price Calculation**: Real-time price breakdown based on strict server-validated pricing rules.
6. **Razorpay Payment**: Secure inline Razorpay payment modal invocation.
7. **Server Verification**: HMAC SHA-256 signature verification transition order to `PRINT_QUEUED`.
8. **Print Agent Fulfillment**: Windows Print Agent claims job (`PRINTING`), dispatches to physical printer (e.g., Kyocera ECOSYS M2040dn KX), and marks `COMPLETED`.
9. **Automated Document Cleanup**: Server unlinks customer printable files from disk 2.5 seconds post-completion.
10. **Receipt Completion**: Animated metallic receipt printer emerges with real order receipt details.

---

## 5. All Major Features
- **OTP Authentication**: Mobile-based login with automatic session setup.
- **Multi-Format Document Upload**: Support for PDF, PNG, JPG, JPEG, WEBP, DOC, DOCX, TXT.
- **Live Print Preview**: Interactive canvas/SVG page renderer.
- **Canonical Pricing Engine**: Strict server-side enforcement of printing rates.
- **Micro Xerox (N-up) Mode**: 2-up, 4-up, 6-up, 9-up, and 16-up layout generation per sheet.
- **Razorpay Live/Test Gateway**: Webhook-free server-side payment verification.
- **Atomic Print Agent Polling**: Polling bridge with token authentication and HTTP 409 conflict protection.
- **Hardware Print Dispatcher**: SumatraPDF execution engine passing `fit`, `duplexlong`, `noduplex`, `paper`, `landscape`, `color`/`monochrome`.
- **Automated Privacy Worker**: Async thread unlinking customer uploads 2.5s post-print.
- **Animated Metallic Receipt UI**: Hood-mounted downward receipt roll showing live order status.
- **Admin Dashboard**: Live management view for active jobs, printer discovery status, revenue metrics, and manual job retries.

---

## 6. Authentication
- Mobile phone number login.
- Simulated/Production OTP verification.
- User session isolation via `localStorage` and server tokens.
- Strict cleanup (`clearUserDocumentSession`) on logout and re-login to ensure no cross-user file leakage.

---

## 7. OTP
- 6-digit OTP delivery flow.
- Admin review login button completely removed.
- Validated server-side before issuing session state.

---

## 8. Document Upload & 9. PDF Support & 10. Multiple PDF Support
- Drag-and-drop & file selector input.
- Automatic page count extraction using PDF parser / client image inspection.
- Support for single and multi-page document packages.

---

## 11. Print Preview
- Canvas & CSS-based visual preview rendering.
- Real-time updates when toggling orientation, paper size, duplex, or Micro Xerox N-up grids.

---

## 12. Canonical Pricing Rules
Strict server-side validated rates (frontend pricing is never trusted):
- **B&W Single Side**: **₹2.00 / page**
- **B&W Double Side**: **₹1.00 / page** (Double-sided discount)
- **Colour Single Side**: **₹6.00 / page**
- **Colour Double Side**: **REMOVED** (Not available)
- **Micro Xerox (N-up)**: **₹3.00 / sheet** (Fixed per sheet rate regardless of N-up grid density)

---

## 13. Single Side & 14. Double Side & 15. Colour Printing
- **Single Side**: Standard single-page per sheet side spooling.
- **Double Side**: Automatic duplexing spooled with `duplexlong` flag in SumatraPDF for hardware duplexers (Kyocera ECOSYS M2040dn KX).
- **Colour Printing**: Dispatched to designated Colour physical printers in `color` mode.

---

## 16. Micro Xerox (N-up)
Combines multiple document pages onto a single physical paper sheet:
- **Grid Options**: **2-up**, **4-up**, **6-up**, **9-up**, **16-up** pages per sheet.
- **Page Ordering**:
  - **Horizontal**: Left-to-right, top-to-bottom layout.
  - **Vertical**: Top-to-bottom, left-to-right layout.
- **Backend Rendering**: Executed via Python `pypdf` (`blank_page.merge_scaled_page(...)`) inside `print_dispatcher.py` / `print_agent.py` prior to print spooling.

---

## Detailed Print Settings
- **Paper Size**: `A4` (210x297mm), `Letter` (8.5x11in), `Legal` (8.5x14in).
- **Orientation**: `Portrait`, `Landscape`.
- **Scaling**:
  - `Fit to Page` (Passes `-print-settings "fit,..."` to SumatraPDF — resolves half-page print bug).
  - `Actual Size` (Passes 100% unscaled dimensions).
- **Margins**: `Normal`, `Minimum`, `None`.
- **Copies**: Integer count (1 to 99).

---

## 17. Razorpay Payment
- Server-side Razorpay order creation (`/api/create-razorpay-order`).
- Live (`rzp_live_*`) and Test key environment configuration.
- Client modal trigger.

---

## 18. Print Queue & 19. Print Agent & 20. Physical Printer
- **Server-Side Verification**: HMAC SHA-256 validation of `razorpay_order_id`, `razorpay_payment_id`, and `razorpay_signature`. Sets order status to `PRINT_QUEUED`.
- **Agent Polling**: Local Windows background agent polls `/api/agent/poll` with `X-Print-Agent-Token` header.
- **Atomic Claim**: Agent claims job via `/api/agent/claim/{order_id}`. Duplicate claims return `HTTP 409 Conflict`.
- **Physical Dispatch**: SumatraPDF spools job to target Windows printer (e.g. Kyocera ECOSYS M2040dn KX).

---

## 21. Order Tracking & 22. Admin Dashboard
- **Order Tracking**: Polling endpoint `/api/orders/{order_id}/status` returns live status (`PRINT_QUEUED` -> `PRINTING` -> `COMPLETED` / `DELETED`).
- **Admin Dashboard**: Managed via `admin.html` to review job history, agent heartbeats, online printers, and retry failed jobs.

---

## 23. Document Privacy & 24. Document Deletion
- **Session Privacy**: Uploaded files and cached previews cleared on logout/re-login (`clearUserDocumentSession`).
- **Automated Disk Cleanup**: 2.5 seconds after the agent confirms job completion (`COMPLETED`), a background worker thread (`schedule_secure_document_cleanup`) permanently unlinks the customer document file from disk (`UPLOAD_DIR`).
- **Customer Confirmation**: UI displays status badge: `"✓ Your files are safe. Documents securely deleted post-print."`

---

## 25. Responsive Design
- 100% mobile-first CSS grid/flexbox layout.
- Tested across Android, iPhone (375px+), Tablet (768px+), Laptop/Desktop (1024px+). Zero horizontal scroll overflow.

---

## 26. Support, 27. Privacy Policy, 28. Terms & Conditions, 29. Refund Policy
- **Support**: Integrated customer support section.
- **Legal Docs**: Privacy Policy, Terms & Conditions, and Refund Policy links available in app footer.

---

## 30. Production / Deployment Requirements
- **Frontend / API Deployment**: Vercel Serverless environment (`main.py`, `api/*.py`, `vercel.json`).
- **Durable Storage**: PostgreSQL database (via `DATABASE_URL`) or local SQLite fallback (`storage.py`).
- **Print Agent Host**: Local Windows PC connected to physical USB/Network printers running Python 3.10+ and SumatraPDF CLI.
