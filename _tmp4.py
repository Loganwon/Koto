import re
# Search for all global registrations in presets.umd.js
with open('web/static/vendor/univer/presets.umd.js', encoding='utf-8', errors='replace') as f:
    content = f.read()

# Find all patterns like N.SomeName={} which is browser global registration
pat = re.compile(r'N\.([A-Za-z][A-Za-z0-9_]+)=\{\}')
globals_found = list(dict.fromkeys(pat.findall(content)))  # dedup preserving order
print('Global registrations:', globals_found[:20])
print('Total globals:', len(globals_found))
