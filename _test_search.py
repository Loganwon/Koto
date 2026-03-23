"""Quick test for skill community APIs."""
import urllib.request
import json

BASE = "http://127.0.0.1:5000/api/skillmarket/community"

# Test 1: Catalog - check likes
print("=" * 50)
print("TEST 1: Catalog (likes)")
r = urllib.request.urlopen(f"{BASE}/catalog")
d = json.loads(r.read())
s0 = d["skills"][0]
print(f"  Count: {len(d['skills'])}")
print(f"  First: {s0['name']} | likes={s0.get('likes')}")
assert "likes" in s0, "FAIL: no likes in catalog"
print("  PASS")

# Test 2: Detail - check likes
print("\nTEST 2: Detail (likes)")
sid = d["skills"][0]["id"]
r2 = urllib.request.urlopen(f"{BASE}/skill/{sid}")
d2 = json.loads(r2.read())
sk = d2["skill"]
print(f"  Name: {sk['name']} | likes={sk.get('likes')}")
assert "likes" in sk, "FAIL: no likes in detail"
print("  PASS")

# Test 3: AI Recommend
print("\nTEST 3: AI Recommend (query='翻译')")
req = urllib.request.Request(
    f"{BASE}/ai-recommend",
    data=json.dumps({"query": "翻译"}).encode(),
    headers={"Content-Type": "application/json"},
)
r3 = urllib.request.urlopen(req, timeout=120)
d3 = json.loads(r3.read())
results = d3.get("results", [])
print(f"  total_pool: {d3.get('total_pool')}")
print(f"  results: {len(results)}")
print(f"  used_fallback: {d3.get('used_fallback')}")
for s in results[:5]:
    print(f"    - {s['name']} | likes={s.get('likes')} | src={s.get('source_url', 'N/A')[:60]}")
assert len(results) > 0, "FAIL: no results from AI recommend"
assert "likes" in results[0], "FAIL: no likes in AI recommend results"
print("  PASS")

print("\n" + "=" * 50)
print("ALL TESTS PASSED!")
