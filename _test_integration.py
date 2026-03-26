"""Quick test: verify socket_handler integration with full app."""
import sys, os
sys.path.insert(0, ".")
os.environ["KOTO_SKIP_BACKGROUND"] = "1"

from web.app import app, socketio

# Check socketio exists and has correct type
print(f"Flask app: {type(app).__name__}")
print(f"SocketIO: {type(socketio).__name__}")

# Check /doc namespace handlers are registered
ns_handlers = []
if hasattr(socketio, "server") and socketio.server:
    for ns in (socketio.server.handlers if hasattr(socketio.server, "handlers") else {}):
        if "/doc" in str(ns):
            ns_handlers.append(ns)

# Verify route exists
rules = [r.rule for r in app.url_map.iter_rules() if "editor" in r.rule]
print(f"Editor routes: {rules}")

# Test /editor route
with app.test_client() as c:
    r = c.get("/editor")
    print(f"GET /editor: {r.status_code}")

print("INTEGRATION TEST COMPLETE")
