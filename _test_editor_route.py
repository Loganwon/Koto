"""Quick test: verify /editor Flask route works."""
from flask import Flask
from web.blueprints.pages import pages_bp

app = Flask(__name__, static_folder="web/static")
app.register_blueprint(pages_bp)

with app.test_client() as c:
    r = c.get("/editor")
    print(f"GET /editor: {r.status_code}")
    if r.status_code == 200:
        data = r.data.decode("utf-8")
        checks = {
            "socket.io CDN": "socket.io" in data,
            "main.css link": "main.css" in data,
            "main.js script": "main.js" in data,
            "univer-container": "univer-container" in data,
            "right-ai-panel": "right-ai-panel" in data,
        }
        for k, v in checks.items():
            status = "PASS" if v else "FAIL"
            print(f"  [{status}] {k}")

    r2 = c.get("/editor/assets/main.css")
    print(f"GET /editor/assets/main.css: {r2.status_code} ({len(r2.data):,} bytes)")

    r3 = c.get("/editor/assets/main.js")
    print(f"GET /editor/assets/main.js: {r3.status_code} ({len(r3.data):,} bytes)")

print("ROUTE TEST COMPLETE")
