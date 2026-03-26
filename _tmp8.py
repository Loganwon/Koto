import re
with open('web/static/vendor/univer/presets.umd.js', encoding='utf-8', errors='replace') as f:
    content = f.read()

# Find all window global registrations: pattern like i.SomeName={} 
# These are set when the UMD runs in browser mode
pat1 = re.compile(r'[Ni]\.([A-Z][A-Za-z0-9]+)=\{\}')
all_globals = list(dict.fromkeys(pat1.findall(content)))
print(f'Globals registered in presets.umd.js ({len(all_globals)} total):')
for g in all_globals:
    print(' ', g)
