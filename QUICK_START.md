# QUICK START: Understanding app.py Dependencies

## TL;DR - The 5-Minute Overview

**What:** C:\repos\Koto\web\app.py is an 17,836-line Flask application
**Problem:** Monolithic structure makes testing & modification hard
**Solution:** Extract 80+ routes into 9 separate blueprint modules
**Effort:** 3-4 months (phased approach)
**Risk:** Medium (has circular dependencies via memory_manager)

---

## 🎯 What to Know in 5 Minutes

### 1. The Flask App is Built in 4 Tiers

`
Tier 1: App Config (lines 1454-1599)
  └─ Flask app, CORS, Prometheus, Swagger, request middleware

Tier 2: Global Singletons (lines 358-6310)
  └─ session_manager, brain, settings_manager, _model_manager
  └─ These are created ONCE and shared by all routes

Tier 3: 80+ Route Handlers (lines 7051-16775)
  └─ Directly on app.py, organized in 9 functional groups
  └─ Depend on Tier 2 singletons

Tier 4: Supporting Infrastructure (throughout)
  └─ Lazy loading, caching, utility functions
`

### 2. The 9 Route Groups (What to Extract)

| # | Name | Size | Complexity | Extract Order |
|---|------|------|-----------|---|
| 1 | SESSION | 95 lines | Simple | 🟢 NOW |
| 2 | PAGE | 50 lines | Simple | 🟢 NOW |
| 3 | WORKSPACE | 95 lines | Simple | 🟢 NOW |
| 4 | SETUP | 200 lines | Simple | 🟢 NOW |
| 5 | SETTINGS | 120 lines | Medium | 🟡 SOON |
| 6 | MODEL/API | 200 lines | Medium | 🟡 SOON |
| 7 | PPT | 150 lines | Medium | 🟡 SOON |
| 8 | VOICE | 500 lines | Medium | ✅ DONE |
| 9 | CHAT | 4,000 lines | Hard | 🔴 LAST |

### 3. The 8 Critical Globals (Singletons)

**NEVER re-instantiate these:**
`python
session_manager      → Stores chat history
brain               → Main AI engine
settings_manager    → User preferences
_model_manager      → Model configuration
`

**ALWAYS use getters for these:**
`python
get_memory_manager() → Long-term memory (lazy)
get_knowledge_base() → Knowledge graph (lazy)
get_client()         → AI client (switches Ollama/Gemini)
get_detected_proxy() → System proxy (lazy)
`

### 4. The Circular Dependency Risk (Know It)

`python
chat_stream()
  └─ reads: _memory_manager.get_context_string()
     └─ DANGER: if memory_manager calls back to chat context
        └─ CIRCULAR LOOP!
`

**Mitigation:** Ensure memory_manager is READ-ONLY from chat history.

### 5. How to Extract a Route Group (The Pattern)

`python
# 1. Create new file: routes/my_routes.py
from flask import Blueprint, request, jsonify

my_routes_bp = Blueprint('my_routes', __name__)

@my_routes_bp.route("/api/myroute", methods=["POST"])
def my_handler():
    # 2. Import globals from app
    from app import session_manager, brain
    
    # 3. Use them
    history = session_manager.load_full(...)
    result = brain.chat(history, ...)
    
    return jsonify(result)

# 3. In app.py, register the blueprint
from routes.my_routes import my_routes_bp
app.register_blueprint(my_routes_bp)
`

---

## 📚 What Documents Do I Read?

### 1. **ANALYSIS_EXECUTIVE_SUMMARY.md** (Start here)
   - Overview of all findings
   - Route groups and complexity
   - Recommended phased approach
   - Safety guidelines
   - **Read time:** 15 min

### 2. **EXTRACTION_SUMMARY.md** (For implementation)
   - Emoji ratings for extraction difficulty
   - Specific globals each route needs
   - How to extract each group
   - Circular dependency check
   - **Read time:** 10 min

### 3. **TECHNICAL_REFERENCE.md** (For developers)
   - Tier-based global organization
   - Lazy loading functions (getter pattern)
   - Safe vs. unsafe globals
   - Dependency isolation matrix
   - **Read time:** 15 min

### 4. **DEPENDENCY_ANALYSIS.md** (Deep dive)
   - Complete globals-to-routes mapping table
   - Class-to-class dependency graph
   - All 80+ routes analyzed
   - Detailed circular risk assessment
   - **Read time:** 30 min

---

## 🚦 Decision Trees

### "Should I extract this route group now?"

`
Does it use lazy-loaded globals (_memory_manager, _client)?
  ├─ Yes → ⚠️ Wait for Phase 2
  └─ No → Does it use session_manager, brain?
      ├─ Yes (but only reads) → 🟡 Phase 2
      └─ No → 🟢 Extract NOW!
`

### "I broke chat_stream after extracting SETTINGS. What happened?"

`
Did you use get_client() getter?
  ├─ Yes → Check if other route groups modified _client
  └─ No → ❌ Use get_client() instead of direct _client access

Did you import chat_stream into settings routes?
  ├─ Yes → ❌ Remove circular import
  └─ No → Memory manager context issue (check DEPENDENCY_ANALYSIS.md)
`

### "Can I extract CHAT routes now?"

`
Have you refactored memory_manager context handling?
  ├─ No → 🔴 Do NOT extract (circular risk)
  └─ Yes → Have you added tests?
      ├─ No → 🟡 Add tests first
      └─ Yes → 🟢 You can extract!
`

---

## 🧪 Testing Strategy

### Before extraction, add tests:
`python
# tests/test_session_routes.py
def test_get_sessions():
    from app import session_manager
    sessions = session_manager.list_all()
    assert isinstance(sessions, list)

def test_session_crud():
    from app import session_manager
    # Create, read, update, delete
    ...
`

### After extraction, verify:
`python
# tests/test_session_routes_extracted.py
def test_extracted_get_sessions():
    from routes.session_routes import session_bp
    # Test the blueprint routes
    with app.test_client() as client:
        response = client.get('/api/sessions')
        assert response.status_code == 200
`

---

## 📊 Progress Tracking

`
Current State: 17,836 lines in single file
              80+ routes, 100+ globals, 15+ classes

Phase 1 (Weeks 1-2): Extract 4 route groups (400 lines)
  ✓ SESSION routes (95 lines)
  ✓ PAGE routes (50 lines)
  ✓ WORKSPACE routes (95 lines)
  ✓ SETUP routes (200 lines)
  Result: app.py → 17,436 lines

Phase 2 (Weeks 3-6): Extract 3 route groups (600 lines)
  ✓ SETTINGS routes (120 lines)
  ✓ MODEL/API routes (200 lines)
  ✓ PPT routes (150 lines)
  Result: app.py → 16,836 lines

Phase 3 (Weeks 7-10): Extract CHAT routes (4,000 lines)
  ✓ Refactor memory_manager context
  ✓ Extract chat_stream, chat, chat_with_file
  Result: app.py → 12,836 lines

Phase 4 (Weeks 11-12): Infrastructure consolidation
  ✓ Create core/singletons.py
  ✓ Create core/client_manager.py
  ✓ Create helpers/system_instruction.py
  Result: Final structure, ~3,000 lines in app.py
`

---

## ⚠️ Common Mistakes

### ❌ "I'll just import _memory_manager directly"
**Wrong:** It might be None on first import
**Right:** Use get_memory_manager() getter function

### ❌ "Let me re-instantiate session_manager in my blueprint"
**Wrong:** Creates duplicate, loses chat history
**Right:** Import from app: rom app import session_manager

### ❌ "I'll put all 80 routes in separate files"
**Wrong:** Too granular, creates complexity
**Right:** Group by functional area (9 groups, see EXTRACTION_SUMMARY)

### ❌ "Chat extraction should happen first"
**Wrong:** Most complex, circular risk, blocks other work
**Right:** Extract simple routes first (SESSION, PAGE, WORKSPACE)

### ❌ "I don't need to test after extraction"
**Wrong:** Easy to break lazy loading or circular refs
**Right:** Test each route group independently

---

## 🆘 Getting Help

### If you hit a circular import error:
1. Check DEPENDENCY_ANALYSIS.md section 5 (Circular Dependency Risks)
2. Ensure you're using getter functions (TECHNICAL_REFERENCE.md)
3. Verify route blueprints don't import each other

### If chat_stream breaks after extraction:
1. Check memory_manager context (ANALYSIS_EXECUTIVE_SUMMARY.md)
2. Verify _client is accessed via get_client()
3. Review EXTRACTION_SUMMARY.md section on memory_manager

### If lazy loading fails:
1. Check that you're calling getter functions, not accessing globals
2. Review TECHNICAL_REFERENCE.md Tier 2 globals
3. Ensure _model_manager initialized via _init_model_manager()

---

## 📞 Document Reference Map

`
Want to know...                          → Read...
─────────────────────────────────────────────────────────────
What routes exist?                       → EXTRACTION_SUMMARY.md
How complex is extraction?               → EXTRACTION_SUMMARY.md
Which globals affect my route?           → TECHNICAL_REFERENCE.md
What's the circular risk?                → DEPENDENCY_ANALYSIS.md
Should I extract now?                    → ANALYSIS_EXECUTIVE_SUMMARY.md
How do I use getter functions?           → TECHNICAL_REFERENCE.md
What are singletons?                     → TECHNICAL_REFERENCE.md
Can I extract my routes together?        → TECHNICAL_REFERENCE.md
What's the phase 1 plan?                 → ANALYSIS_EXECUTIVE_SUMMARY.md
`

---

## ✨ Key Insight

**app.py is well-designed, but monolithic.**

The good news:
- Clear separation of concerns (AI, files, settings, voice)
- Already has some blueprints (agent, skill, voice, ppt)
- Singleton pattern minimizes state duplication
- Getter functions for lazy loading

The improvement:
- Extract remaining 80 routes into 9 functional blueprints
- Reduce app.py from 17,836 to ~3,000 lines
- Enable parallel development
- Simplify testing

The effort:
- 3-4 months, phased approach
- Phase 1 (easy): 2 weeks
- Phase 2 (medium): 2-3 weeks
- Phase 3 (hard): 3-4 weeks
- Phase 4 (consolidate): 1 week

---

**Ready to start? Begin with ANALYSIS_EXECUTIVE_SUMMARY.md → Then EXTRACTION_SUMMARY.md → Then TECHNICAL_REFERENCE.md**

All three were created in your project root: C:\repos\Koto\
