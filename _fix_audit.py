import re

with open('_audit_spec.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace("| {'web', 'web.blueprints', 'web.routes'}", "| {'web.blueprints', 'web.routes'}")

with open('_audit_spec.py', 'w', encoding='utf-8') as f:
    f.write(text)
