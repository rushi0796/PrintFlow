# PrintFlow — AI & Vibe Coding Rules

This document serves as the permanent set of binding directives for all future AI agents and software engineers working on the PrintFlow codebase.

---

## 1. Permanent Core Rules (1–30)

1. **Never rebuild the application unnecessarily**: Work within the existing PrintFlow framework; do not refactor from scratch or discard working architecture.
2. **Inspect existing code before modifying it**: Use code search (`grep_search`, `find_by_name`) to understand existing symbol definitions before editing.
3. **Search repository before creating duplicate functions**: Audit `storage.py`, `main.py`, `print_dispatcher.py`, and `script.js` before adding new utility functions.
4. **Preserve working functionality**: Never break existing features when implementing new changes or refactoring.
5. **Do not break OTP**: Preserve mobile number validation and OTP authentication flows in `login.html` / `login.js`.
6. **Do not break Razorpay**: Maintain server-side HMAC SHA-256 signature verification in `main.py` / `api/verify-payment.py`.
7. **Do not break Print Agent**: Keep `print_agent.py`, `printer_manager.py`, and `print_dispatcher.py` token authentication and claim contracts fully operational.
8. **Do not replace physical printing with browser printing**: The end target MUST always be physical paper output spooled via the local Windows Print Agent and SumatraPDF CLI.
9. **Do not fake payment success**: Payment verification must strictly validate real Razorpay signatures.
10. **Do not fake print completion**: Print completion state must originate from actual hardware/agent execution callbacks.
11. **Do not fake document deletion**: Document cleanup MUST physically unlink target document files from server disk after 2.5 seconds.
12. **Never trust frontend pricing**: All order calculations MUST be independently recalculated and validated server-side.
13. **Validate pricing server-side**: Reject or override any order payload where the amount is lower than `calculate_order_amount(...)`.
14. **Never expose secrets**: Do not write sensitive keys (`RAZORPAY_KEY_SECRET`, `PRINT_AGENT_TOKEN`) to client-side bundles, public API outputs, or logs.
15. **Never hardcode Razorpay secrets**: Retrieve API credentials from environment variables with fallback defaults strictly reserved for local development.
16. **Never expose document URLs publicly**: Protect printable uploads; serve only via authenticated streams or agent tokens.
17. **Keep documents user-scoped**: Ensure session storage and file references belong strictly to the authenticated mobile session.
18. **Prevent cross-user document access**: Clear temporary upload state on logout and session expiration.
19. **Clear temporary upload state on logout**: Invoke `clearUserDocumentSession()` on logout and session resets.
20. **Do not restore old temporary PDFs after re-login**: Re-logging in MUST always present a 100% clean document upload state.
21. **Use durable backend storage**: Utilize PostgreSQL or local SQLite storage (`storage.py`) for order persistence.
22. **Do not rely on Vercel `/tmp` for permanent order data**: Serverless ephemeral storage is temporary; write persistent state to database schemas.
23. **Do not create duplicate print jobs**: Maintain order deduplication and enforce idempotent payment verification.
24. **Payment callbacks must be idempotent**: Multiple calls to `/api/verify-payment` with the same order ID must return consistent state without duplicating queue entries.
25. **Agent claims must be idempotent/safe**: Return `HTTP 409 Conflict` if an agent attempts to claim an order that is already in `PRINTING` status.
26. **Preserve queue ordering**: Process `PRINT_QUEUED` orders sequentially based on timestamp FIFO.
27. **Test physical printing**: Verify that SumatraPDF flags (`fit`, `duplexlong`/`noduplex`, `paper`, `landscape`) render properly on physical printers (Kyocera ECOSYS M2040dn KX).
28. **Fix root causes instead of hiding errors**: Never swallow exceptions silently with empty `try/except` blocks or fallback dummy values to hide bugs.
29. **Do not delete tests to make the test suite pass**: Maintain and update `scratch/test_printflow_full_production_suite.py` whenever schema or business rules change.
30. **Do not commit `.env` or credentials**: Ensure `.env` and credential files remain in `.gitignore`.

---

## 2. What To Use & What To Avoid

### What To Use
- Existing project architecture (`main.py`, `storage.py`, `print_agent.py`, `print_dispatcher.py`).
- Existing SumatraPDF CLI driver with explicit `-print-settings "fit,duplexlong,..."`.
- Existing `pypdf` N-up grid layout synthesizer (`create_n_up_pdf`).
- Existing Razorpay payment integration and server verification.
- Existing automated production QA suite (`scratch/test_printflow_full_production_suite.py`).

### What To Avoid
- Unnecessary third-party dependencies or framework replacements.
- Duplicate database access layers or inline SQL re-writes outside `storage.py`.
- Browser window `window.print()` fallbacks in place of local Windows Print Agent spooling.
- Fake timers, synthetic sound effects, or mock static success states on the receipt page.
- Unjustified visual redesigns breaking existing PrintFlow design patterns.

---

## 3. Error Handling Rules

Every production-critical component must handle:
1. **Network Interruptions**: Retries with exponential backoff on agent polling and status requests.
2. **API Verification Failures**: Clear HTTP 400 response on invalid Razorpay signature.
3. **Missing Document Files**: HTTP 404 response when attempting to claim or download an unlinked or deleted document.
4. **Printer Failures**: Agent captures spooler error messages and posts job status `FAILED` with diagnostic details (`print_error`).
5. **Agent Offline State**: Frontend polling alerts user when Print Agent is offline (`/api/agent/status`).
6. **Concurrent Claim Conflicts**: Atomic database transaction returning HTTP 409 Conflict.

---

## 4. AI Coding Boundaries

AI agents operating on PrintFlow MUST NOT:
- Alter system architecture without explicit user authorization and documentation updates.
- Modify `print_agent.py` or `print_dispatcher.py` CLI arguments unless fixing a verified hardware spooling bug.
- Swallow or disable failing test assertions to force test suite passes.
- Commit hardcoded secrets or remove security headers.
