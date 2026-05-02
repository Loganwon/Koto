"""Test DOCX source and meta endpoints."""
import urllib.request, urllib.error, json

docId = 'f63f191a421e'
base = 'http://127.0.0.1:5000'

# Test /source
try:
    with urllib.request.urlopen(f'{base}/api/editor/docs/{docId}/source', timeout=10) as r:
        ct = r.headers.get('Content-Type')
        data = r.read()
        print(f'[OK] source: status={r.status}, content-type={ct}, bytes={len(data)}')
except urllib.error.HTTPError as e:
    print(f'[FAIL] source: HTTP {e.code} - {e.read().decode()}')
except Exception as e:
    print(f'[FAIL] source: {e}')

# Test /meta
try:
    with urllib.request.urlopen(f'{base}/api/editor/docs/{docId}/meta', timeout=10) as r:
        meta = json.loads(r.read())
        print(f'[OK] meta: status={r.status}, pageWidth={meta.get("pageWidth")}, defaultFont={repr(meta.get("defaultFont"))}')
except urllib.error.HTTPError as e:
    print(f'[FAIL] meta: HTTP {e.code} - {e.read().decode()}')
except Exception as e:
    print(f'[FAIL] meta: {e}')

print('Done.')
