from http.server import BaseHTTPRequestHandler
import json


class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        try:
            from main import agent_status_endpoint
            response = agent_status_endpoint()
        except Exception as err:
            response = {
                "status": "error",
                "agent_online": False,
                "discovered_printers": [],
                "config": {},
                "message": str(err)
            }

        body = json.dumps(response).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        self.wfile.write(body)