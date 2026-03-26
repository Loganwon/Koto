"""
Script to merge Logan/20260326 into main and resolve conflicts.
Run with: python _do_merge.py
"""
import subprocess
import sys
import os

REPO = r"c:\Users\12524\Desktop\Koto"
log = open(os.path.join(REPO, "_merge_output.txt"), "w", encoding="utf-8")

def run(cmd, check=True):
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace")
    msg = f"$ {' '.join(cmd)}\n"
    if r.stdout.strip():
        msg += r.stdout.strip() + "\n"
    if r.stderr.strip():
        msg += "[STDERR] " + r.stderr.strip() + "\n"
    msg += f"Exit: {r.returncode}\n\n"
    print(msg, end="")
    log.write(msg)
    log.flush()
    if check and r.returncode != 0:
        log.close()
        sys.exit(f"Command failed: {' '.join(cmd)}")
    return r

print("=== STEP 1: Current branch and status ===")
run(["git", "branch", "--show-current"])
run(["git", "status", "--porcelain"], check=False)

print("=== STEP 2: Stash any dirty files ===")
run(["git", "stash", "push", "-m", "pre-merge-stash"], check=False)

print("=== STEP 3: Merge Logan/20260326 (no-ff, no-commit) ===")
r = run(["git", "merge", "--no-ff", "--no-commit", "Logan/20260326"], check=False)

print("=== STEP 4: Check conflicts ===")
status = run(["git", "status", "--porcelain"])
conflicts = [l for l in status.stdout.splitlines() if l.startswith("UU")]
print(f"Conflicts: {conflicts}")

if conflicts:
    print("=== STEP 5: Resolve conflicts by taking Logan/20260326 version ===")
    for line in conflicts:
        fname = line[3:].strip()
        print(f"Resolving {fname} with Logan/20260326 version...")
        run(["git", "checkout", "Logan/20260326", "--", fname])

print("=== STEP 6: Stage all ===")
run(["git", "add", "-A"])

print("=== STEP 7: Commit merge ===")
run(["git", "commit", "-m", "merge: Logan/20260326 → main (token tracking, skill auto-open, file storage path fixes)"])

print("=== STEP 8: Apply stash back ===")
run(["git", "stash", "pop"], check=False)

print("=== STEP 9: Final status ===")
run(["git", "log", "--oneline", "-5"])
run(["git", "status", "--porcelain"], check=False)

print("=== DONE. Review above, then run: git push origin main ===")
log.write("=== DONE ===\n")
log.close()
