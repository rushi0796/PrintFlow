# PrintFlow — Continuous AI Project Memory

This document contains the live state, architectural decisions, recent test results, and development memory for the PrintFlow repository.

---

## 1. Current Project Status

- **System Status**: Fully Production Ready.
- **Current Task**: Implemented & verified Multiple File Upload System with real XHR progress tracking, controlled queue runner, drag & drop, per-file retry, clear all, and add more features.
- **Current File**: `home.html`, `script.js`, `style.css`
- **Active Git Commit**: `22105ad` (Preparing commit for Multiple File Upload System)
- **Deployment Target**: Vercel (`https://print-flow-mu.vercel.app`) & Local Windows Print Agent (`print_agent.py`)

---

## 2. Completed Milestones & Architectural Decisions

1. **Multiple File Upload System**:
   - Built a real multiple-file upload engine in `script.js` and `home.html`.
   - **Real XHR Byte Progress**: Tracks actual bytes sent via `xhr.upload.onprogress` with zero fake timers or hardcoded percentages.
   - **Controlled Queue Processing**: Sequential file upload runner preserving exact file selection order.
   - **Drag & Drop Zone**: Interactive drop zone on `home.html` supporting PDF, PNG, JPG, JPEG, WEBP, DOC, DOCX, TXT.
   - **Queue Controls**: `[ Choose Files ]`, `[ + Add More Files ]` (appends without resetting queue), `[ Clear All ]` (aborts XHRs and resets queue), per-file `[ × ]` remove/cancel, and per-file `[ Retry ]` for failed uploads.
   - **Compact & Expandable UI**: Compact status header summary ("Uploading 5 files", "✓ 5 files uploaded successfully") with an expandable/collapsible per-file detail list.
   - **Deduplication & Validation**: Client-side deduplication key (`name + size + lastModified`) and backend extension validation.
   - **Downstream Compatibility**: Syncs `fileName`, `pdfPageCount`, `backendFilePath`, and `fileListDetails` into `localStorage` so existing single-file and multi-file print configurations operate seamlessly.

2. **Canonical Pricing Engine**:
   - Strictly enforced pricing rules: B&W Single ₹2/page, B&W Double ₹1/page, Colour Single ₹6/page, Colour Double REMOVED, Micro Xerox ₹3/sheet.
   - Independent server-side price validation in `main.py` overrides any client payload tampering.

3. **Full-Page & Duplex Hardware Spooling**:
   - Fixed SumatraPDF half-page print bug by passing explicit `-print-settings "fit,..."` in `print_dispatcher.py`.
   - Fixed hardware duplexing by passing `duplexlong` in SumatraPDF settings string for double-sided spooling on Kyocera ECOSYS M2040dn KX.

4. **Micro Xerox N-up Synthesis**:
   - Integrated native `pypdf` grid generator (`create_n_up_pdf`) supporting 2-up, 4-up, 6-up, 9-up, and 16-up layout generation per sheet.

5. **Automated 2.5-Second Document Privacy Cleanup**:
   - Implemented background worker thread (`schedule_secure_document_cleanup`) in `main.py` that permanently unlinks customer document files from disk 2.5 seconds post-completion (`PRINTED` -> `DELETED`).
   - Added session cleanup (`clearUserDocumentSession`) in `login.js` and `script.js` to ensure clean state across user logins.

6. **Animated Metallic Receipt Printer UI**:
   - Built hood-mounted receipt printer component in `success.html` displaying live order details, real-time backend status polling, and free order retry capability.

---

## 3. Current Bugs & Recent Fixes

- **Recent Fix 1 (Multiple File Upload System)**: Replaced legacy single-file upload handler with a dynamic, real-progress, multi-file queue manager supporting drag & drop, add more, clear all, and retry.
- **Recent Fix 2 (Database Column Persistence)**: Added missing print contract columns (`scale_mode`, `print_mode`, `pages_per_sheet`, `page_order`, `customer_mobile`) to `storage.py` database schema and migration list.
- **Current Bugs**: None. All automated test suites passing 100%.

---

## 4. Test Results & Quality Assurance

- **Multi-File Upload Test Suite**: `scratch/test_multi_file_upload_suite.py` -> **100% PASSED**
  - Single PDF Upload: PASS
  - PNG / JPG / WEBP Image Uploads: PASS
  - DOC / DOCX / TXT Document Uploads: PASS
  - Unallowed Extension (.exe) Rejection: PASS
- **Production QA Suite**: `scratch/test_printflow_full_production_suite.py` -> **100% PASSED**

---

## 5. Next Recommended Task

- Commit all changes to git and push to `origin/master`.
