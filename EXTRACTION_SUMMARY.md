# DEPENDENCY EXTRACTION SUMMARY

## Quick Reference: Which Globals Each Route Group Uses

### 1️⃣ CHAT ROUTES (High Coupling - Keep or Major Refactor)
Lines: 7210-13250 | Routes: /api/chat, /api/chat/stream, /api/chat/file, /api/chat/interrupt

**Reads:**
- brain (KotoBrain singleton)
- session_manager (SessionManager singleton)
- MODEL_MAP, MODEL_INFO
- _memory_manager (lazy)
- _interrupt_manager
- API_KEY
- CHAT_DIR, WORKSPACE_DIR

**Writes:** 
- (None directly, but updates via session_manager.append_and_save())

**Risk Level:** ⚠️ HIGH - Circular risk via memory_manager

**Extraction Difficulty:** 🔴 HARD - Requires dependency injection refactor

---

### 2️⃣ SESSION ROUTES (Low Coupling - Easy Extract) ✅
Lines: 7105-7200 | Routes: /api/sessions (CRUD operations)

**Reads:**
- session_manager (SessionManager singleton)
- CHAT_DIR

**Writes:**
- (None, session_manager handles storage)

**Risk Level:** ✅ NONE - Isolated dependencies

**Extraction Difficulty:** 🟢 EASY

**How to Extract:**
`python
# routes/session_routes.py
from flask import Blueprint, request, jsonify

session_bp = Blueprint('session', __name__)

@session_bp.route("/api/sessions", methods=["GET"])
def get_sessions():
    from app import session_manager, CHAT_DIR
    # ... implementation
`

---

### 3️⃣ WORKSPACE/FILE ROUTES (Low Coupling - Easy Extract) ✅
Lines: 15441-15535 | Routes: /api/workspace/*, /api/open-workspace, /api/open-file

**Reads:**
- WORKSPACE_DIR
- UPLOAD_DIR
- FileOperator class methods

**Writes:** (None)

**Risk Level:** ✅ NONE - File I/O only

**Extraction Difficulty:** 🟢 EASY

---

### 4️⃣ SETTINGS ROUTES (Medium Coupling - Extract with Care) ⚠️
Lines: 15658-15768 | Routes: /api/settings*, /api/local-model/*, /api/switch-to-mini

**Reads:**
- settings_manager (SettingsManager singleton)
- _user_settings_cache, _user_settings_lock
- _client (for model switching)
- _get_local_model_config()
- PROJECT_ROOT

**Writes:**
- _user_settings_cache

**Risk Level:** ⚠️ MEDIUM - _client switching is stateful

**Extraction Difficulty:** 🟡 MEDIUM - Requires careful client management

**Key Caution:** Ensure _client is obtained via getter function, not direct access

---

### 5️⃣ MODEL/API ROUTES (Medium Coupling - Extract with Care) ⚠️
Lines: 15241-15441 | Routes: /api/info, /api/v1/models*, /api/analyze

**Reads:**
- API_KEY
- MODEL_MAP, MODEL_INFO
- _model_manager (lazy initialized)
- brain.analyze_task()

**Writes:** (None)

**Risk Level:** ⚠️ MEDIUM - Lazy initialization dependency

**Extraction Difficulty:** 🟡 MEDIUM - Use _init_model_manager() getter

---

### 6️⃣ PPT ROUTES (Medium Coupling - Extract with Care) ⚠️
Lines: 15165-15241 | Routes: /api/ppt/download, /api/ppt/session/*

**Reads:**
- PPTMasterOrchestrator (lazy proxy)
- PPTGenerationPipeline (lazy proxy)
- session_manager
- WORKSPACE_DIR, UPLOAD_DIR

**Writes:** (None)

**Risk Level:** ⚠️ MEDIUM - Lazy module initialization

**Extraction Difficulty:** 🟡 MEDIUM - Already using lazy proxies

**Note:** PPT system already has partial blueprint at ppt_api_routes.py

---

### 7️⃣ PAGE ROUTES (Zero Coupling - Easy Extract) ✅
Lines: 7051-7102 | Routes: /, /app, /file-network, /knowledge-graph, /mini, /mobile

**Reads:**
- PROJECT_ROOT (for template paths)

**Writes:** (None)

**Risk Level:** ✅ NONE - Pure rendering

**Extraction Difficulty:** 🟢 EASY

---

### 8️⃣ VOICE ROUTES (Already Extracted) ✅
Lines: 1745-1751 (registered via blueprint)

**Status:** Already a separate blueprint: voice_api_enhanced -> voice_bp

**Routes:** /api/voice/* (engines, record, recognize, listen, stream, stop, commands, stt)

---

### 9️⃣ SETUP/DIAGNOSE ROUTES (Low Coupling - Easy Extract) ✅
Lines: 15973-16149 | Routes: /api/setup/*, /api/diagnose, /api/browse

**Reads:**
- API_KEY
- settings_manager
- get_client() (for test endpoint)
- PROJECT_ROOT

**Writes:** (None to globals)

**Risk Level:** ✅ NONE - Setup only

**Extraction Difficulty:** 🟢 EASY

---

## CRITICAL SINGLETONS (DO NOT DUPLICATE!)

These MUST remain singular across the app:

`
session_manager = SessionManager()      @ line 6074
brain = KotoBrain()                      @ line 7046
settings_manager = SettingsManager()    @ line 1957
_model_manager = (lazy init)            @ line 2041
`

**When extracting routes:**
- Import these from app.py: rom app import session_manager
- Or use getter functions: rom app import get_memory_manager()
- NEVER re-instantiate them

---

## EXTRACTION ORDER (Recommended)

### PHASE 1: No Risk Routes (Extract Immediately)
1. Session routes → routes/session_routes.py
2. Page routes → routes/page_routes.py
3. Workspace routes → routes/workspace_routes.py
4. Setup/Diagnose routes → routes/setup_routes.py

### PHASE 2: Medium Risk Routes (Extract with Dependency Injection)
1. Settings routes → routes/settings_routes.py (careful with _client)
2. Model/API routes → routes/model_routes.py (use getter functions)
3. PPT routes → routes/ppt_routes.py (use lazy proxies)

### PHASE 3: High Risk Routes (Requires Refactor)
1. Chat routes → routes/chat_routes.py (major refactor: inject brain, memory_manager)

### PHASE 4: Keep in app.py (Core Infrastructure)
1. Blueprint registration system
2. Client/model initialization & lazy loading
3. Proxy detection & setup in background
4. App configuration & middleware

---

## DEPENDENCY INJECTION PATTERN FOR EXTRACTED ROUTES

`python
# routes/chat_routes.py
from flask import Blueprint, request, jsonify

chat_bp = Blueprint('chat', __name__)

@chat_bp.route("/api/chat", methods=["POST"])
def chat():
    # Import getters/singletons from app
    from app import session_manager, get_memory_manager
    from app import brain, MODEL_MAP, API_KEY
    
    if not API_KEY:
        return jsonify({"error": "API key not configured"}), 400
    
    data = request.json
    session_name = data.get("session")
    
    # Use singleton methods
    history = session_manager.load_full(f"{session_name}.json")
    
    # Use getter for lazy-loaded globals
    memory_mgr = get_memory_manager()
    context = memory_mgr.get_context_string(...)
    
    # Use singleton class for AI operations
    result = brain.chat(history, user_input)
    
    session_manager.append_and_save(...)
    return jsonify(result)

# In app.py
from routes.chat_routes import chat_bp
app.register_blueprint(chat_bp)
`

---

## CIRCULAR DEPENDENCY CHECK

### ✅ Safe (One-way dependencies)
- Route → Utils (one-way, never back)
- Route → ContextAnalyzer (one-way, never back)
- Route → SessionManager (one-way, never back)

### ⚠️ Potential Risk (Bidirectional)
- Route ← → brain ← → memory_manager
  - **Solution:** Ensure memory_manager.get_context() is READ-ONLY
  - Don't call routes from memory extraction functions

- Route ← → settings_manager ← → _client
  - **Solution:** Use getter functions, not direct global access
  - _client switching should be atomic

### ❌ Avoid (Would create loops)
- Route A → Helper B → Route A (circular import)
  - **Pattern:** Helpers should NEVER import route functions

---

## FILE SIZE BREAKDOWN

**Original:** 17,836 lines, 896 KB

**Estimated After Extraction:**

| File | Lines | Purpose |
|------|-------|---------|
| app.py | ~3000 | App init, config, blueprint registration |
| routes/chat_routes.py | ~4000 | Chat operations (largest) |
| routes/session_routes.py | ~200 | Session CRUD |
| routes/workspace_routes.py | ~300 | File access |
| routes/settings_routes.py | ~400 | User preferences |
| routes/model_routes.py | ~300 | Model info & analysis |
| routes/ppt_routes.py | ~300 | PPT operations |
| routes/page_routes.py | ~200 | Template rendering |
| routes/setup_routes.py | ~200 | Setup & diagnostics |
| routes/voice_routes.py | ~500 | Voice operations (already separate) |
| core/singletons.py | ~200 | Singleton management |
| core/client_manager.py | ~300 | Client initialization |

**Total: ~10,000 lines** (app.py reduced by 43%, more maintainable)

---

## NEXT STEPS

1. ✅ Review this dependency analysis for your codebase
2. 📋 Create tests for each route group to ensure isolation
3. 🔧 Start with PHASE 1 routes (no risk)
4. 🧪 Verify blueprint imports work (use get_* functions)
5. 📚 Document the new module structure
6. 🚀 Deploy incrementally, test after each extraction

