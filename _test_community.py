"""Quick validation of community AI recommend code path."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web'))
sys.path.insert(0, os.getcwd())

from app.core.llm.gemini import GeminiProvider
print('Step 1: GeminiProvider import OK')

from app.api.skill_marketplace_routes import _COMMUNITY_SKILLS, _COMMUNITY_SKILLS_BY_ID
print(f'Step 2: _COMMUNITY_SKILLS has {len(_COMMUNITY_SKILLS)} skills')
print(f'Step 3: First skill: {_COMMUNITY_SKILLS[0]["name"]}')
print(f'Step 4: Skill IDs: {[s["id"] for s in _COMMUNITY_SKILLS[:3]]}...')
print('ALL CHECKS PASSED')
