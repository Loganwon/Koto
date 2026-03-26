# Search for 'UniverPresets' or 'createUniver' or 'Univer' globals
with open('web/static/vendor/univer/presets.umd.js', encoding='utf-8', errors='replace') as f:
    content = f.read()

# Find all unique IIFE patterns (each sub-module in the bundle)
import re
# Pattern: (function(X,Y){...}) where Y is factory getting called with X.GlobalName
top_iifes = re.findall(r'\(function\(\w,\w\)\{[^}]{0,200}self,\w\.\w+', content)
print('IIFE starters found:', len(top_iifes))
for t in top_iifes[:5]:
    print(' ', t[:120])

# Direct search for UniverPresets
idx = content.find('UniverPresets')
if idx >= 0:
    print('\nUniverPresets found at offset', idx, ':', content[max(0,idx-50):idx+100])
else:
    print('\nUniverPresets NOT found in file')
    
# Search for createUniver
idx2 = content.find('createUniver')
if idx2 >= 0:
    print('\ncreateUniver found at offset', idx2, ':', content[max(0,idx2-50):idx2+100])
else:
    print('\ncreateUniver NOT found in file')
