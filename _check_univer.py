import urllib.request
import re

def check(url):
    try:
        req = urllib.request.urlopen(url, timeout=15)
        content = req.read(5000).decode('utf-8', errors='replace')
        # Look for the pattern: root["SomeName"] = factory()
        matches = re.findall(r'\["([A-Za-z][A-Za-z0-9_.]+)"\]', content[:3000])
        matches2 = re.findall(r"'([A-Za-z][A-Za-z0-9_.]+)'", content[:3000])
        print(f"  [{url.split('/')[4]}] found [\": {matches[:8]}")
        print(f"  [{url.split('/')[4]}] found [': {matches2[:8]}")
        print(f"  first 800 chars: {content[:800]}")
        return content
    except Exception as e:
        print(f"  ERROR: {e}")
        return ""

pkgs = [
    "https://unpkg.com/@univerjs/presets/lib/umd/index.js",
    "https://unpkg.com/@univerjs/preset-docs-core/lib/umd/index.js",
    "https://unpkg.com/@univerjs/preset-sheets-core/lib/umd/index.js",
]
for p in pkgs:
    check(p)
