import re

with open('koto.spec', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace("    'web', 'web.audio_overview',", "    'web', 'web.app', 'web.audio_overview',")

with open('koto.spec', 'w', encoding='utf-8') as f:
    f.write(text)
