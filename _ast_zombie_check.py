import ast
import os
import sys

def parse_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        return ast.parse(f.read(), filename=filepath)

def analyze_directory(directory="app"):
    print(f"Analyzing {directory} for unused functions and classes...")
    # This is a basic AST check. For full analysis, Pylance or Vulture is recommended.
    all_defs = set()
    all_calls = set()
    
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.py') and not file.startswith('__'):
                filepath = os.path.join(root, file)
                try:
                    tree = parse_file(filepath)
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            if not node.name.startswith('_'): # Skip private/dunder
                                all_defs.add((node.name, filepath, node.lineno))
                        elif isinstance(node, ast.ClassDef):
                            all_defs.add((node.name, filepath, node.lineno))
                        elif isinstance(node, ast.Name):
                            all_calls.add(node.id)
                        elif isinstance(node, ast.Attribute):
                            all_calls.add(node.attr)
                except Exception as e:
                    print(f"Error parsing {filepath}: {e}")
                    
    zombies = []
    for name, path, line in all_defs:
        # A very basic heuristic: if a defined name is never referenced anywhere, it MIGHT be dead code
        if name not in all_calls:
            zombies.append(f"{path}:{line} - Potential zombie: {name}")
            
    return zombies

if __name__ == "__main__":
    dirs_to_check = ['app', 'web', 'scripts']
    for d in dirs_to_check:
        if os.path.exists(d):
            zombies = analyze_directory(d)
            if zombies:
                print(f"--- Potential Zombie Code in {d} ---")
                for z in sorted(zombies):
                    print(z)
            else:
                print(f"No obvious zombies found in {d} with basic AST heuristic.")
