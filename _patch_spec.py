import os

spec_file = 'koto.spec'
with open(spec_file, 'r', encoding='utf-8') as f:
    content = f.read()

# We need to append the dynamic hidden imports logic right after the hiddenimports list is defined.
# I will find "hiddenimports = [" and match its closing bracket.
import ast

# Since it's a python script, let's just append the dynamic logic at the bottom of the file if it's not already there.
# But wait, hiddenimports is passed to Analysis(... hiddenimports=hiddenimports ...).
# So I must inject it BEFORE Analysis( ... ) !

injection_code = """
# ── Dynamic Auto-discovery for hiddenimports ──
def _discover_hidden_imports(base_dir, base_pkg):
    import os
    imports = []
    if not os.path.exists(base_dir): return imports
    for root, _, files in os.walk(base_dir):
        for f in files:
            if f.endswith('.py') and not f.startswith('_'):
                rel_path = os.path.relpath(root, base_dir)
                pkg = base_pkg
                if rel_path != '.':
                    pkg = f"{base_pkg}.{rel_path.replace(os.sep, '.')}"
                mod = f[:-3]
                imports.append(f"{pkg}.{mod}")
            elif f == '__init__.py':
                rel_path = os.path.relpath(root, base_dir)
                pkg = base_pkg
                if rel_path != '.':
                    pkg = f"{base_pkg}.{rel_path.replace(os.sep, '.')}"
                imports.append(pkg)
    return imports

hiddenimports.extend(_discover_hidden_imports(os.path.join(ROOT, 'app'), 'app'))
hiddenimports.extend(_discover_hidden_imports(os.path.join(ROOT, 'web'), 'web'))

"""

if "_discover_hidden_imports" not in content:
    idx = content.find('a = Analysis(')
    if idx != -1:
        new_content = content[:idx] + injection_code + content[idx:]
        with open(spec_file, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("Successfully injected dynamic hidden imports discovery into koto.spec")
    else:
        print("Could not find Analysis block in koto.spec")
else:
    print("koto.spec already contains dynamic hidden imports logic")
