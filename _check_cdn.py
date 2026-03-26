import urllib.request

urls = [
    "https://unpkg.com/@univerjs/presets/lib/umd/index.js",
    "https://unpkg.com/@univerjs/preset-docs-core/lib/umd/index.js",
    "https://unpkg.com/@univerjs/preset-sheets-core/lib/umd/index.js",
    "https://unpkg.com/@univerjs/core/lib/umd/index.js",
]

for url in urls:
    try:
        req = urllib.request.Request(url, method="HEAD")
        resp = urllib.request.urlopen(req, timeout=10)
        print(f"OK  {resp.status}  {url} -> final: {resp.url}")
    except urllib.error.HTTPError as e:
        print(f"ERR {e.code}  {url}")
    except Exception as e:
        print(f"FAIL {type(e).__name__}: {url}")
