"""Test file import endpoint."""
import sys, os, json, glob
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import urllib.request
import urllib.error

BASE = "http://127.0.0.1:5000"

def post_file(url, filepath):
    boundary = "----FormBoundaryXyz123"
    filename = os.path.basename(filepath)
    with open(filepath, "rb") as f:
        fdata = f.read()
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + fdata + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return e.code, body

# 1. Test list
try:
    with urllib.request.urlopen(f"{BASE}/api/editor/docs", timeout=5) as r:
        data = json.loads(r.read())
    print(f"[OK] List: {len(data['docs'])} docs")
except Exception as e:
    print(f"[FAIL] List: {e}")
    sys.exit(1)

# 2. Test DOCX import
docx_candidates = glob.glob(r"C:\Users\12524\Desktop\*.docx")
docx = r"C:\Users\12524\Desktop\王宇轩-简历（美元）.docx" if os.path.exists(r"C:\Users\12524\Desktop\王宇轩-简历（美元）.docx") else (docx_candidates[0] if docx_candidates else None)
if docx:
    code, resp = post_file(f"{BASE}/api/editor/docs/import", docx)
    if code == 201:
        print(f"[OK] DOCX import: id={resp.get('id')}, size={resp.get('size')}, ext={resp.get('sourceExt')}")
    else:
        print(f"[FAIL] DOCX import: {code} -> {resp[:500]}")
else:
    print(f"[SKIP] No DOCX found on Desktop")

# 3. Test PPTX import (find any .pptx on Desktop)
import glob
pptx_files = glob.glob(r"C:\Users\12524\Desktop\*.pptx")
if not pptx_files:
    pptx_files = glob.glob(r"C:\Users\12524\Desktop\**\*.pptx", recursive=True)[:1]
if pptx_files:
    pptx = pptx_files[0]
    print(f"Testing PPTX: {pptx}")
    code, resp = post_file(f"{BASE}/api/editor/docs/import", pptx)
    if code == 201:
        print(f"[OK] PPTX import: id={resp.get('id')}, size={resp.get('size')}, ext={resp.get('sourceExt')}")
    else:
        print(f"[FAIL] PPTX import: {code} -> {str(resp)[:500]}")
else:
    print("[SKIP] No .pptx found on Desktop")

# 4. Test XLSX import
xlsx_files = glob.glob(r"C:\Users\12524\Desktop\*.xlsx")
if not xlsx_files:
    xlsx_files = glob.glob(r"C:\Users\12524\Desktop\**\*.xlsx", recursive=True)[:1]
if xlsx_files:
    xlsx = xlsx_files[0]
    print(f"Testing XLSX: {xlsx}")
    code, resp = post_file(f"{BASE}/api/editor/docs/import", xlsx)
    if code == 201:
        print(f"[OK] XLSX import: id={resp.get('id')}, size={resp.get('size')}, ext={resp.get('sourceExt')}")
    else:
        print(f"[FAIL] XLSX import: {code} -> {str(resp)[:500]}")
else:
    print("[SKIP] No .xlsx found on Desktop")
