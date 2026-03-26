import re
with open('web/static/vendor/univer/presets.umd.js', encoding='utf-8', errors='replace') as f:
    content = f.read()
# Find what's exported into UniverPresets
idx = content.rfind('UniverPresets={')
ctx = content[idx:idx+500]
print('UniverPresets export context:', ctx)
# Also check for createUniver
pu = content.rfind('createUniver')
print('last createUniver:', content[pu-10:pu+80])
