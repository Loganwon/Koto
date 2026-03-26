"""Quick end-to-end sanity test for the koto-patch.js / /editor route fix."""
import sys, re

PATCH = r"web/static/univer-dist/assets/koto-patch.js"
INDEX = r"web/static/univer-dist/index.html"

errors = []
ok = []

# ── 1. koto-patch.js: installFetchInterceptor must NOT be called in the first IIFE
with open(PATCH, encoding="utf-8") as f:
    src = f.read()

# Split on the boundary between the two IIFEs
parts = src.split("// ═══════════════════════════════════════════════════════════════")
if len(parts) < 2:
    errors.append("Cannot split koto-patch.js into two IIFEs — content unexpectedly changed")
else:
    first_iife = parts[0]
    rest = "\n".join(parts[1:])
    if "installFetchInterceptor" in first_iife:
        errors.append("installFetchInterceptor is still called/referenced in the FIRST IIFE!")
    else:
        ok.append("First IIFE does NOT reference installFetchInterceptor ✓")

# ── 2. koto-patch.js: installFetchInterceptor must be defined and called in second IIFE
second_iife_src = rest
call_matches = [m.start() for m in re.finditer(r'\binstallFetchInterceptor\b', second_iife_src)]
if len(call_matches) >= 2:
    ok.append(f"installFetchInterceptor found {len(call_matches)} times in second IIFE (call + definition) ✓")
else:
    errors.append(f"installFetchInterceptor only found {len(call_matches)} times in second IIFE (expected ≥2)")

# The call must come before the function keyword (hoisting test is visual; let's at least confirm both exist)
call_idx = second_iife_src.find("installFetchInterceptor();")
def_idx = second_iife_src.find("function installFetchInterceptor(")
if call_idx != -1 and def_idx != -1:
    ok.append("Call + definition both present in same IIFE ✓")
    if call_idx < def_idx:
        ok.append("Call is before textual definition — relies on hoisting (valid JS function declaration) ✓")
else:
    errors.append("Could not confirm both call and definition exist")

# ── 3. index.html: version string must be consistent across all assets
with open(INDEX, encoding="utf-8") as f:
    html = f.read()

versions = re.findall(r'\?v=([\w]+)"', html)
unique = set(versions)
if len(unique) == 1:
    ok.append(f"All assets use same version string: {unique.pop()} ✓")
else:
    errors.append(f"Mixed version strings in index.html: {unique}")

# ── 4. Flask /editor route: Cache-Control header present
try:
    from web.app import app
    with app.test_client() as c:
        r = c.get("/editor")
        cc = r.headers.get("Cache-Control", "")
        if "no-cache" in cc or "no-store" in cc:
            ok.append(f"GET /editor Cache-Control: '{cc}' ✓")
        else:
            errors.append(f"GET /editor missing no-cache header — got: '{cc}'")

        r2 = c.get("/editor/assets/koto-patch.js")
        if r2.status_code == 200:
            ok.append(f"GET /editor/assets/koto-patch.js → 200 OK, {len(r2.data)} bytes ✓")
        else:
            errors.append(f"GET /editor/assets/koto-patch.js → {r2.status_code}")

        # version in served HTML
        served_html = r.data.decode("utf-8", errors="replace")
        versions_served = re.findall(r'\?v=([\w]+)"', served_html)
        unique_served = set(versions_served)
        ok.append(f"Served HTML has version(s): {unique_served}")
except Exception as e:
    import traceback
    errors.append(f"Flask test failed: {e}\n{traceback.format_exc()}")

# ── Report ──────────────────────────────────────────────────────────────────
print("\n=== TEST RESULTS ===\n")
for msg in ok:
    print(f"  [PASS] {msg}")
if errors:
    print()
    for msg in errors:
        print(f"  [FAIL] {msg}")
    sys.exit(1)
else:
    print("\nAll checks passed.")
    sys.exit(0)
