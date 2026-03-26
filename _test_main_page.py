"""Test: verify main page has file assistant panel embedded."""
import sys, os
sys.path.insert(0, ".")
from flask import Flask
from web.blueprints.pages import pages_bp

app = Flask(__name__, 
            template_folder="web/templates",
            static_folder="web/static")
app.register_blueprint(pages_bp)

with app.test_client() as c:
    r = c.get("/")
    print(f"GET /: {r.status_code}")
    if r.status_code == 200:
        data = r.data.decode("utf-8")
        checks = {
            "fileAssistantPanel": "fileAssistantPanel" in data,
            "toggleFileAssistant()": "toggleFileAssistant()" in data,
            "fa-panel-iframe": "fa-panel-iframe" in data,
            "file-assistant-panel CSS": "file-assistant-panel" in data,
            "navEditorBtn": "navEditorBtn" in data,
        }
        for k, v in checks.items():
            status = "PASS" if v else "FAIL"
            print(f"  [{status}] {k}")

print("MAIN PAGE TEST COMPLETE")
