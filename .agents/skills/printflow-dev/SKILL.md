---
name: printflow-dev
description: Specialized development workflow guide, architecture standards, and security rules for the PrintFlow repository.
---

# PrintFlow Agent & Skill Guidelines

This skill equips Antigravity agents with project-specific knowledge for maintaining, extending, and testing the PrintFlow web application.

---

## 🏗️ Architecture & Core Components

1. **Backend Framework**: Python FastAPI (`main.py` and Vercel serverless functions in `api/`).
2. **Serverless Endpoints**:
   - `POST /api/create-order` & `POST /api/create-razorpay-order`: Generates real Razorpay order IDs via `https://api.razorpay.com/v1/orders`.
   - `POST /api/verify-payment` & `POST /api/verify-razorpay-payment`: Server-side HMAC-SHA256 signature verification.
   - `POST /api/upload-pdf`: Handles multi-file uploads for printable formats (`.pdf`, `.png`, `.jpg`, `.jpeg`, `.webp`, `.doc`, `.docx`, `.txt`).
3. **Frontend Stack**: Native HTML5, CSS3 glassmorphism (`style.css`), vanilla JavaScript (`script.js`, `login.js`).
4. **Vercel Routing**: Defined in `vercel.json` rewrite rules.

---

## 🔒 Security & Credentials Enforcement

- **Environment Variables Only**: `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` MUST ALWAYS be read dynamically via `os.environ.get(...)`.
- **Zero Secrets in Version Control**: Never hardcode credentials in HTML, JS, Python, or markdown files.
- **Git Security**: `.env` MUST remain listed in `.gitignore`.
- **Safe Diagnostic Logging**: Logs may report variable presence (`has_key_id`, `is_live_key`, `masked_key_id`), but **NEVER** log or print `RAZORPAY_KEY_SECRET`.

---

## 💰 Pricing & Order Calculation Standard

- **Pricing Formula**: `Total Amount (₹) = Page Count × Copies × ₹2`.
- **Multi-File Uploads**:
  - Image / Document files count as 1 page per file.
  - Multi-page PDFs sum total pages across documents.
  - Total page count is passed to frontend `localStorage` and sent in Paise (`amount * 100`) to Razorpay.

---

## 🧪 Testing & Verification Protocol

Before declaring any task completed:
1. Run local test suite (`python scratch/verify_all_requirements.py`).
2. Validate HTTP endpoints using FastAPI `TestClient` or `requests.post`.
3. Check `git status` to ensure `.env` is un-tracked and clean.
