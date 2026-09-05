# PrintFlow — Continuous AI Project Memory

This document contains the live state, architectural decisions, recent test results, and development memory for the PrintFlow repository.

---

## 1. Current Project Status

- **System Status**: Fully Production Ready.
- **Current Task**: Establishing required project documentation suite (`/docs/`) and synchronizing git repository state.
- **Current File**: `/docs/memory.md`
- **Active Git Commit**: `c6c69cd` (`feat: complete print job contract persistence in storage database`)
- **Deployment Target**: Vercel (`https://print-flow-mu.vercel.app`) & Local Windows Print Agent (`print_agent.py`)

---

## 2. Completed Milestones & Architectural Decisions

1. **Canonical Pricing Engine**:
   - Strictly enforced pricing rules: B&W Single ₹2/page, B&W Double ₹1/page, Colour Single ₹6/page, Colour Double REMOVED, Micro Xerox ₹3/sheet.
   - Independent server-side price validation in `main.py` overrides any client payload tampering.

2. **Full-Page & Duplex Hardware Spooling**:
   - Fixed SumatraPDF half-page print bug by passing explicit `-print-settings "fit,..."` in `print_dispatcher.py`.
   - Fixed hardware duplexing by passing `duplexlong` in SumatraPDF settings string for double-sided spooling on Kyocera ECOSYS M2040dn KX.

3. **Micro Xerox N-up Synthesis**:
   - Integrated native `pypdf` grid generator (`create_n_up_pdf`) supporting 2-up, 4-up, 6-up, 9-up, and 16-up layout generation per sheet.

4. **Automated 2.5-Second Document Privacy Cleanup**:
   - Implemented background worker thread (`schedule_secure_document_cleanup`) in `main.py` that permanently unlinks customer document files from disk 2.5 seconds post-completion (`PRINTED` -> `DELETED`).
   - Added session cleanup (`clearUserDocumentSession`) in `login.js` and `script.js` to ensure clean state across user logins.

5. **Animated Metallic Receipt Printer UI**:
   - Built hood-mounted receipt printer component in `success.html` displaying live order details, real-time backend status polling, and free order retry capability.

---

## 3. Current Bugs & Recent Fixes

- **Recent Fix 1 (Database Column Persistence)**: Added missing print contract columns (`scale_mode`, `print_mode`, `pages_per_sheet`, `page_order`, `customer_mobile`) to `storage.py` database schema and migration list.
- **Recent Fix 2 (Razorpay Order Pre-Save)**: Updated `create_razorpay_order_endpoint` in `main.py` to persist initial order entries in `storage.py` before returning checkout tokens.
- **Current Bugs**: None. All automated production suite tests passing 100%.

---

## 4. Test Results & Quality Assurance

- **Test Suite**: `scratch/test_printflow_full_production_suite.py`
- **Result**: `100% PASSED` (0 errors, 0 failures).
  - Canonical Pricing Calculations: PASS
  - Backend Price Tampering Protection: PASS
  - Razorpay Verification & Queue Transition: PASS
  - PrintAgent Polling & Atomic Claim (HTTP 409 Conflict): PASS
  - 2.5s Automated Document File Cleanup & Order Retry: PASS

---

## 5. Deployment & Infrastructure Status

- **Vercel Web App**: Configured via `vercel.json` and direct Vercel serverless function handlers in `api/`.
- **Durable Storage**: PostgreSQL when `DATABASE_URL` is set, with automatic SQLite3 fallback (`orders/printflow.sqlite3`).
- **Windows Print Agent**: Operational on Windows host connected to Kyocera ECOSYS M2040dn KX.

---

## 6. Next Recommended Task

- Run final git status check, stage all `/docs/` documentation files, commit, and push to `origin/master`.
