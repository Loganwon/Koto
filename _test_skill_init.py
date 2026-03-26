"""Quick test: verify SkillManager init restores user-set skills correctly."""
import sys, json, shutil
from pathlib import Path
sys.path.insert(0, 'app')

from core.skills.skill_manager import SkillManager

REAL_SETTINGS = Path("config/user_settings.json")
BACKUP = Path("config/user_settings.json.test_bak")

# Back up real settings
shutil.copy2(REAL_SETTINGS, BACKUP)

# Write a test settings file with api_doc_generator enabled=True
with open(REAL_SETTINGS, "w", encoding="utf-8") as f:
    json.dump({"skills": {"api_doc_generator": {"enabled": True}}}, f)

SkillManager._initialized = False
SkillManager._registry = {}
SkillManager._def_registry = {}

try:
    SkillManager._ensure_init()
    reg = SkillManager._registry
    api_enabled = reg.get("api_doc_generator", {}).get("enabled")
    chart_enabled = reg.get("chart_analyst", {}).get("enabled")
    data_enabled = reg.get("data_analysis", {}).get("enabled")
    print(f"api_doc_generator enabled: {api_enabled}  (expected: True)")
    print(f"chart_analyst enabled: {chart_enabled}  (expected: False)")
    print(f"data_analysis enabled: {data_enabled}  (expected: True - builtin default)")
    
    all_enabled = [sid for sid, s in reg.items() if s.get("enabled")]
    print(f"\nTotal enabled: {len(all_enabled)}: {all_enabled}")
    
    assert api_enabled is True, "api_doc_generator should be True (from user_settings)"
    assert chart_enabled is False, "chart_analyst should be False (not in user_settings)"
    assert data_enabled is True, "data_analysis should be True (builtin default)"
    print("\nALL ASSERTIONS PASSED")
finally:
    # Restore
    shutil.copy2(BACKUP, REAL_SETTINGS)
    BACKUP.unlink()
    SkillManager._initialized = False
    SkillManager._registry = {}
