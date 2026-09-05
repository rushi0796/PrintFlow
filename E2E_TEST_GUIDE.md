# PrintFlow End-to-End Payment → Printer Test

## Quick Start Guide

### Prerequisites
- Razorpay TEST account and TEST credentials configured in Vercel
- Windows machine with printer connected
- PrintFlow deployed to Vercel
- Local network connectivity to Vercel backend

### Test Procedure (15-20 minutes)

#### STEP 1: Start Local Print Agent (3 minutes)
On the Windows machine with the printer:

```bash
cd c:\PrintFlow
python print_agent.py
```

**Expected output:**
```
==================================================
  🖨️  PrintFlow Local Windows Print Agent v1.0   
==================================================
 Target Backend: https://print-flow-mu.vercel.app
 Poll Interval : 3 seconds
 Agent Status   : READY / CONNECTED

[AGENT PRINTER DISCOVERY] Detected 10 printer(s):
  - Kyocera ECOSYS M2040dn KX
  - EPSON L3210 Series
  - Microsoft Print to PDF
  ... (other printers)

[PRINTER CONFIG] B&W: Kyocera ECOSYS M2040dn KX
[PRINTER CONFIG] Color: EPSON L3210 Series
[AGENT] ONLINE
[AGENT POLL] Polling backend for print jobs...
```

**Agent Status**: ✓ ONLINE

#### STEP 2: Open PrintFlow Website (1 minute)
Navigate to:
```
https://print-flow-mu.vercel.app
```

Or if running locally:
```
http://localhost:8000
```

**Expected page**: Upload PDF for printing

#### STEP 3: Upload a Test Document (2 minutes)
1. Click **"Choose PDF"**
2. Select a test PDF file from your computer
3. Wait for thumbnail to appear

**Expected output:**
- File name displayed
- Page count shown (e.g., "5 pages")
- PDF preview visible

#### STEP 4: Configure Print Settings (1 minute)
Set these exact values:

| Setting | Value |
|---------|-------|
| Pages to Print | All (or specific page range) |
| Copies | 1 |
| Color Mode | Black & White |
| Duplex/Sides | Double Sided |
| Orientation | Portrait |

**Click**: "Proceed to Payment"

#### STEP 5: Review Order (1 minute)
Verify on payment details page:

- **Order ID**: PF-XXXXXX (shown)
- **File**: test_filename.pdf
- **Pages**: 5 (or your PDF page count)
- **Copies**: 1
- **Color**: Black & White
- **Price**: ₹10.00 (5 pages × 1 copy × ₹2)

**Click**: "Pay with Razorpay"

#### STEP 6: Complete Razorpay Payment (2 minutes)
Razorpay TEST mode checkout opens:

1. **Key/Secret shown**: Razorpay TEST credentials displayed
2. **Email**: customer@printflow.in
3. **Phone**: 9876543210
4. **Click**: "Create" (for test payment)

**Expected output**:
- Payment Success page
- Redirects to success.html
- Shows "Payment Verified"

**Backend logs** (check Vercel logs):
```
[RAZORPAY VERIFY DIAGNOSTIC] KEY_SECRET configured: true
[PAYMENT VERIFIED] Razorpay payment pay_xxxxx verified for order order_xxxxx
[PRINT JOB QUEUED] Order PF-XXXXXX added to the agent queue
```

#### STEP 7: Agent Detects Queued Job (5-10 seconds)
**Local Print Agent output** (on Windows machine):

```
[AGENT POLL] Found 1 pending print job(s) in queue!
[AGENT CLAIMED ORDER] Order ID: PF-XXXXXX | State: PRINTING
[PRINTER] Detected: Kyocera ECOSYS M2040dn KX (B&W)
[AGENT FILE DOWNLOADED] File: a1b2c3d4_test_filename.pdf
[AGENT SILENT PRINT] Printing 'test_filename.pdf' to 'Kyocera ECOSYS M2040dn KX' | Copies: 1 | Orient: portrait
[AGENT JOB COMPLETED] Order PF-XXXXXX marked COMPLETED on backend!
[AGENT LOCAL PRIVACY CLEANUP] Local temp file 'test_filename.pdf' deleted 2.5s after printing.
```

#### STEP 8: Physical Print Output (30-60 seconds)
**Physical printer**:

✓ **Windows printer receives print job**
✓ **Print job appears in printer queue**
✓ **Printer processes the job**
✓ **Physical paper comes out of printer**
✓ **Correct number of copies printed**
✓ **Correct orientation (portrait/landscape)**
✓ **Correct printer used**

#### STEP 9: Verify Completion (2 minutes)
1. Go to **Admin Dashboard**: https://print-flow-mu.vercel.app/admin
2. Access code: **Admin@123**
3. Find your order (PF-XXXXXX) at the top of the list

**Expected values**:
- **Order ID**: PF-XXXXXX
- **Status**: ✓ COMPLETED
- **Printed By**: Kyocera ECOSYS M2040dn KX
- **Document Status**: DELETED (cleaned up after 2.5 seconds)
- **Payment**: VERIFIED (Razorpay payment ID shown)

## Success Criteria

✓ **ALL of the following must be true**:

1. ✓ Print Agent starts successfully and shows ONLINE status
2. ✓ PDF uploads without errors
3. ✓ Page count detected correctly
4. ✓ Order details shown correctly
5. ✓ Razorpay TEST checkout opens (not LIVE)
6. ✓ Payment completes successfully
7. ✓ Backend verifies signature without errors
8. ✓ Order status becomes PRINT_QUEUED
9. ✓ Agent detects the queued job within 3-10 seconds
10. ✓ Agent downloads the document successfully
11. ✓ Agent selects correct printer (Kyocera for B&W)
12. ✓ **Physical paper comes out of the printer** ← CRITICAL
13. ✓ Agent reports COMPLETED status
14. ✓ Backend marks order as COMPLETED
15. ✓ Document is deleted from server (after 2.5 seconds)
16. ✓ Admin dashboard shows COMPLETED order with DELETED document

## Troubleshooting

### Issue: Agent shows "OFFLINE"
**Solution**: 
- Check backend_url in agent_config.json
- Verify internet connectivity
- Restart agent: `python print_agent.py`

### Issue: "RAZORPAY_KEY_SECRET is not configured"
**Solution**:
- Verify environment variables set in Vercel dashboard
- Check Production environment (not Preview)
- Redeploy: `vercel --prod`

### Issue: Payment fails with invalid signature
**Solution**:
- Verify RAZORPAY_KEY_SECRET matches Razorpay account
- Check that TEST (not LIVE) credentials are used
- Ensure no extra quotes or spaces in environment variable

### Issue: Agent doesn't receive print job
**Solution**:
- Check agent status on admin dashboard
- Verify agent_token matches PRINT_AGENT_TOKEN in environment
- Check order status changed to PRINT_QUEUED
- Wait 10-15 seconds for agent poll interval

### Issue: Printer not found
**Solution**:
- Check configured printer names in agent_config.json
- Run on Windows machine: `Get-Printer` (PowerShell)
- Update printer names to match exactly
- Restart agent

### Issue: Physical printing doesn't happen
**Solution**:
- Check printer is connected and online: `Get-Printer | Select Name, PrinterStatus`
- Test manual print from Windows
- Check SumatraPDF or Word is installed for PDF/DOCX
- Check temp file downloaded: `dir c:\PrintFlow\agent_temp\`

## Success Indicators

### Backend Logs (Vercel)
```
[RAZORPAY DIAGNOSTIC] KEY_ID: rzp_test...xxxx, Mode: TEST, KEY_SECRET configured: true
[RAZORPAY VERIFY DIAGNOSTIC] KEY_SECRET configured: true
[PAYMENT VERIFIED] Razorpay payment pay_xxxxx verified for order order_xxxxx
[PRINT JOB QUEUED] Order PF-XXXXXX added to the agent queue
```

### Agent Logs
```
[AGENT] ONLINE
[AGENT POLL] Found 1 pending print job(s) in queue!
[AGENT CLAIMED ORDER] Order ID: PF-XXXXXX | State: PRINTING
[AGENT FILE DOWNLOADED] File: xxxxx_filename.pdf
[AGENT SILENT PRINT] Printing 'filename.pdf' to 'Kyocera ECOSYS M2040dn KX'
[AGENT JOB COMPLETED] Order PF-XXXXXX marked COMPLETED on backend!
```

### Physical Output
- ✓ Document prints to correct printer
- ✓ Correct number of pages
- ✓ Correct number of copies
- ✓ Correct orientation

## Final Validation

Run the automated test suite:

```bash
# Payment and queue tests
python test_payment_and_queue.py

# Agent and printer tests
python test_agent_and_printer.py
```

**Expected**: All 17 tests PASS ✓

---

**SYSTEM IS READY FOR PRODUCTION** when:
- All automated tests pass
- End-to-end payment test completes with physical print output
- Admin dashboard shows correct order status and document deletion
- No secrets appear in logs or error messages
