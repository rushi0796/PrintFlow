from main import app
from main import create_print_order, health, upload_pdf


app.add_api_route("/api/health", health, methods=["GET"])
app.add_api_route("/api/print-order", create_print_order, methods=["POST"])
app.add_api_route("/api/upload-pdf", upload_pdf, methods=["POST"])
