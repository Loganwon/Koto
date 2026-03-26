import re
with open('web/static/vendor/univer/presets.umd.js', encoding='utf-8', errors='replace') as f:
    content = f.read()

# Search ALL patterns: x=typeof globalThis...  which is the browser fallback
# These patterns register globals
pat = re.compile(r'([A-Za-z_]+)=typeof globalThis')
hits = list(dict.fromkeys(pat.findall(content)))
print('All typeof globalThis roots:', hits[:20])

# Also find function calls that set globals in browser mode e.g. i(e.UniverCore=...)
pat2 = re.compile(r'[A-Za-z]\(([A-Za-z_]+\.UniverCore)[,=\)]')
hits2 = pat2.findall(content)
print('UniverCore usage:', hits2[:5])

# Search for 'UniverCore' in context 
import sys
idx = 0
count = 0
found = []
while count < 5:
    idx = content.find('UniverCore', idx)
    if idx == -1:
        break
    found.append((idx, content[max(0,idx-20):idx+40]))
    idx += 10
    count += 1
print('UniverCore occurrences (first 5):')
for pos, snip in found:
    print(f'  @{pos}: {snip!r}')
