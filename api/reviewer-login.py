import os
import json

def handler(request):
    try:
        body = json.loads(request.body) if hasattr(request, "body") and request.body else {}
        access_key = (body.get("access_key") or "").strip()
        mobile = (body.get("mobile") or "9999999999").strip()
        
        expected_key = os.environ.get("REVIEWER_ACCESS_KEY", "Reviewer@2026")
        if access_key != expected_key:
            return {
                "statusCode": 401,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"detail": "Invalid Reviewer Access Key"})
            }

        if not mobile.startswith("+91"):
            mobile = f"+91{mobile.lstrip('+91')}"

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "status": "success",
                "message": "Reviewer authentication successful",
                "mobile": mobile,
                "is_reviewer": True
            })
        }
    except Exception as err:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"detail": str(err)})
        }
