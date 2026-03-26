import re
with open('web/static/vendor/univer/presets.umd.js', encoding='utf-8', errors='replace') as f:
    content = f.read()
# Find createUniver function body - look at the full function v
idx = content.rfind('function v(p){')
if idx == -1:
    idx = content.rfind('function v(')
print(f'createUniver function at {idx}')
ctx = content[idx:idx+1500]
print(ctx)
