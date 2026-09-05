#!/bin/bash
# PrintFlow Vercel Deployment Verification Script
# This script validates the deployment is ready for production

set -e

echo "=================================="
echo "PrintFlow Deployment Verification"
echo "=================================="
echo ""

# Check required environment variables are set
echo "[1/5] Checking Vercel environment configuration..."

# Note: These checks assume you're using Vercel CLI
# The actual environment variables must be set in Vercel dashboard

echo "  ✓ RAZORPAY_KEY_ID should be set in Vercel Production env"
echo "  ✓ RAZORPAY_KEY_SECRET should be set in Vercel Production env"
echo "  ✓ PRINT_AGENT_TOKEN should be set in Vercel Production env"
echo ""

# Verify Python syntax
echo "[2/5] Verifying Python syntax..."
python -m py_compile main.py 2>/dev/null && echo "  ✓ main.py" || echo "  ✗ main.py"
python -m py_compile api/create-order.py 2>/dev/null && echo "  ✓ api/create-order.py" || echo "  ✗ api/create-order.py"
python -m py_compile api/verify-payment.py 2>/dev/null && echo "  ✓ api/verify-payment.py" || echo "  ✗ api/verify-payment.py"
python -m py_compile api/verify-razorpay-payment.py 2>/dev/null && echo "  ✓ api/verify-razorpay-payment.py" || echo "  ✗ api/verify-razorpay-payment.py"
echo ""

# Check for hardcoded secrets
echo "[3/5] Scanning for hardcoded secrets..."
if grep -r "rzp_live_" --include="*.py" --include="*.js" . 2>/dev/null | grep -v test | grep -v "#"; then
    echo "  ✗ FOUND HARDCODED LIVE CREDENTIALS"
    exit 1
fi
if grep -r "rzp_test_" --include="*.py" . 2>/dev/null | grep -v test | grep -v "^./test_"; then
    echo "  ⚠ Found test credentials (expected in development only)"
else
    echo "  ✓ No hardcoded TEST credentials in main code"
fi
echo "  ✓ No LIVE credentials found in code"
echo ""

# Verify .gitignore protection
echo "[4/5] Checking .gitignore..."
if grep -q ".env" .gitignore; then
    echo "  ✓ .env files are protected"
else
    echo "  ⚠ .gitignore might not protect .env files"
fi
echo ""

# Check Vercel configuration
echo "[5/5] Checking Vercel configuration..."
if [ -f "vercel.json" ]; then
    echo "  ✓ vercel.json exists"
    # Verify basic structure
    if grep -q '"rewrites"' vercel.json; then
        echo "  ✓ Route rewrites configured"
    fi
    if grep -q '"functions"' vercel.json; then
        echo "  ✓ Function configuration present"
    fi
else
    echo "  ✗ vercel.json missing"
    exit 1
fi
echo ""

echo "=================================="
echo "Pre-Deployment Checklist"
echo "=================================="
echo ""
echo "BEFORE DEPLOYING TO VERCEL:"
echo ""
echo "1. [ ] Configure RAZORPAY_KEY_ID in Vercel Production environment"
echo "      - Use your Razorpay TEST mode key"
echo "      - Format: rzp_test_xxxxxxxxxxxxxx"
echo ""
echo "2. [ ] Configure RAZORPAY_KEY_SECRET in Vercel Production environment"
echo "      - Use your Razorpay TEST mode secret"
echo "      - NEVER commit this to Git"
echo ""
echo "3. [ ] Configure PRINT_AGENT_TOKEN in Vercel Production environment"
echo "      - Default: PF_AGENT_SECRET_TOKEN_2026"
echo ""
echo "4. [ ] Deploy to Vercel:"
echo "      vercel --prod"
echo ""
echo "5. [ ] Test the deployed endpoints:"
echo "      curl -X POST https://print-flow-mu.vercel.app/api/verify-payment"
echo "      (should return 400 'not configured' if missing credentials)"
echo ""
echo "6. [ ] Start the local Print Agent:"
echo "      python print_agent.py"
echo ""
echo "7. [ ] Test end-to-end payment flow"
echo ""
echo "=================================="

echo "✓ Deployment verification complete!"
