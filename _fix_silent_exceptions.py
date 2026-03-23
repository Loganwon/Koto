import os
import re

directories = ['app', 'web']
log_import = 'import logging\nlogger = logging.getLogger(__name__)\n'

# patterns to find except Exception: pass or except: pass
regex = re.compile(r'(except\s+(Exception(?:\s+as\s+[a-zA-Z0-9_]+)?)?\s*:)\s+pass')

fixed_count = 0

for d in directories:
    for root, _, files in os.walk(d):
        for f in files:
            if f.endswith('.py'):
                filepath = os.path.join(root, f)
                with open(filepath, 'r', encoding='utf-8') as file:
                    content = file.read()
                
                if regex.search(content):
                    # Replace 'pass' with 'logger.warning("Silenced exception", exc_info=True)'
                    def replacer(match):
                        # match.group(1) is the 'except [Exception] [as e]:' part
                        ex_part = match.group(1)
                        return f'{ex_part}\n            import logging; logging.getLogger(__name__).warning("Silenced exception caught", exc_info=True)'
                    
                    new_content = regex.sub(replacer, content)
                    with open(filepath, 'w', encoding='utf-8') as file:
                        file.write(new_content)
                    print(f'Fixed silent exception in {filepath}')
                    fixed_count += 1

print(f'Total files modified: {fixed_count}')
