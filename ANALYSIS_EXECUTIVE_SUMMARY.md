# EXECUTIVE SUMMARY: C:\repos\Koto\web\app.py Dependency Analysis

## 📊 File Overview
- **Path:** C:\repos\Koto\web\app.py
- **Size:** 17,836 lines | 896 KB
- **Routes:** 80+ direct routes
- **Classes:** 15+ major classes
- **Global Variables:** 100+ module-level globals
- **Blueprints:** 13+ registered (health, task, agent, skill, voice, ppt, goal, file, job, etc.)

---

## 🎯 Key Findings

### 1. FLASK APP CONFIGURATION
✅ **Status:** Well-structured initialization
- Flask app created at line 1454
- CORS, Sentry, Prometheus, Swagger configured
- Request middleware for ID tracking
- 13 blueprints registered in _register_blueprints_deferred() (lines 1651-1843)

### 2. GLOBAL VARIABLE ECOSYSTEM (100+ globals)

**Tier 0: Core Infrastructure (Immutable)**
- app (Flask), _app_logger, PROJECT_ROOT, CHAT_DIR, WORKSPACE_DIR, UPLOAD_DIR, API_KEY

**Tier 1: Critical Singletons (Must be singular)**
- session_manager (6074) - Chat history
- brain (7046) - Main AI engine  
- settings_manager (1957) - User preferences
- _model_manager (2041) - Model configuration [lazy]

**Tier 2: Lazy-Loaded Caches (Created on first access)**
- _client (651) - Switches between Ollama/Gemini
- _memory_manager (6078) - Long-term memory
- _kb (6079) - Knowledge base
- _detected_proxy (557) - System proxy

**Tier 3: Management Objects**
- _interrupt_manager (326) - Per-session interrupt flags
- _user_settings_cache (364) - Settings JSON cache
- Multiple lazy-load caches for document, PPT, file operations

### 3. ROUTE GROUPS (80+ routes organized in 9 groups)

| Group | Routes | Lines | Coupling | Extract Risk |
|-------|--------|-------|----------|--------------|
| CHAT | 5 | 7210-13250 | 🔴 HIGH | Hard |
| SESSION | 4 | 7105-7200 | ✅ None | Easy ✅ |
| WORKSPACE | 4 | 15441-15535 | ✅ None | Easy ✅ |
| PAGE | 9 | 7051-7102 | ✅ None | Easy ✅ |
| SETTINGS | 9 | 15658-15768 | ⚠️ Medium | Medium ⚠️ |
| MODEL/API | 4 | 15241-15441 | ⚠️ Medium | Medium ⚠️ |
| PPT | 2 | 15165-15241 | ⚠️ Medium | Medium ⚠️ |
| VOICE | 8+ | Blueprint | Isolated | Already extracted ✅ |
| SETUP | 5 | 15973-16149 | ✅ None | Easy ✅ |

### 4. CLASS DEPENDENCY GRAPH

**Core Classes:**
`
FileOperator (2198)
  ↓ reads: WORKSPACE_DIR, settings_manager
  
WebSearcher (2563)
  ↓ reads: client
  
ContextAnalyzer (3428)
  ↓ reads: MODEL_MAP
  
TaskOrchestrator (4087)
  ↓ reads: (recursive subtasks)
  
Utils (5471)
  ↓ static methods, reads nothing
  
SessionManager (5927)
  ↓ reads: CHAT_DIR
  
KotoBrain (6316) [CENTRAL HUB]
  ├─ reads: MODEL_MAP, MODEL_INFO, _model_manager, session_manager
  ├─ calls: ContextAnalyzer, TaskOrchestrator, FileOperator, WebSearcher
  └─ used by: chat(), chat_stream(), chat_with_file()
`

### 5. CIRCULAR DEPENDENCY RISKS

**🔴 HIGH RISK: chat_stream ↔ memory_manager ↔ knowledge_graph**
`
chat_stream()
  └─ calls: _memory_manager.get_context_string()
      └─ may reference: chat session context
          └─ RISK: if memory_manager calls back to ContextAnalyzer
`

**Mitigation:** Ensure memory_manager operations are read-only from history.

**⚠️ MEDIUM RISK: _client switching in settings routes**
`
local_model_switch()
  └─ reassigns: _client (global state change)
      └─ RISK: if chat_stream reads _client during switch
`

**Mitigation:** Use getter function get_client() with atomic switching.

**✅ NO RISK: Helpers → Routes (one-way only)**
- Utils → Routes (never back)
- ContextAnalyzer → Routes (never back)
- Helpers never import routes

### 6. GLOBALS USAGE HEATMAP

**Most Used Globals:**
1. session_manager - Used by: chat, session routes, brain
2. brain - Used by: chat routes, model routes
3. MODEL_MAP - Used by: chat routes, model routes
4. settings_manager - Used by: settings routes, setup routes
5. _memory_manager - Used by: chat_stream only
6. API_KEY - Used by: chat, setup, model routes

**Least Used (Safe to extract):**
- PAGE_ROUTES_ONLY: None
- WORKSPACE_ROUTES_ONLY: WORKSPACE_DIR, UPLOAD_DIR
- SESSION_ROUTES_ONLY: session_manager, CHAT_DIR

---

## 📋 DETAILED GLOBALS-TO-ROUTES MAPPING

### ✅ EASY EXTRACTION (Safe Immediately)

**SESSION ROUTES** (7105-7200)
- Reads: session_manager, CHAT_DIR
- Writes: session_manager (new sessions)
- Risk: None

**PAGE ROUTES** (7051-7102)
- Reads: Nothing (template rendering)
- Writes: None
- Risk: None

**WORKSPACE ROUTES** (15441-15535)
- Reads: WORKSPACE_DIR, UPLOAD_DIR, FileOperator
- Writes: None
- Risk: None

**SETUP ROUTES** (15973-16149)
- Reads: API_KEY, settings_manager, get_client()
- Writes: None (read-only)
- Risk: None

### ⚠️ MEDIUM EXTRACTION (Dependency Injection Required)

**SETTINGS ROUTES** (15658-15768)
- Reads: settings_manager, _client (mutable)
- Writes: _user_settings_cache, _client
- Risk: Medium (client mode switching is stateful)
- Solution: Use get_client() getter function

**MODEL/API ROUTES** (15241-15441)
- Reads: API_KEY, MODEL_MAP, MODEL_INFO, _model_manager (lazy), brain
- Writes: None
- Risk: Medium (lazy initialization dependency)
- Solution: Call _init_model_manager() getter

**PPT ROUTES** (15165-15241)
- Reads: PPTMasterOrchestrator (lazy), session_manager, WORKSPACE_DIR
- Writes: None (files written via lazy proxies)
- Risk: Medium (lazy module loading)
- Solution: Use existing lazy proxy pattern

### 🔴 HARD EXTRACTION (Major Refactor Required)

**CHAT ROUTES** (7210-13250)
- Reads: brain, session_manager, MODEL_MAP, _memory_manager, _interrupt_manager, API_KEY
- Writes: session_manager.append_and_save()
- Risk: High (complex interdependencies, circular with memory_manager)
- Solution: Requires refactoring memory_manager context injection

---

## 🚀 RECOMMENDED EXTRACTION ROADMAP

### PHASE 1: Zero-Risk Routes (1-2 weeks)
**Extract:** Session + Page + Workspace + Setup routes
**Total:** ~400 lines
**Benefit:** Reduce app.py to ~17,400 lines, cleaner structure
**Timeline:** 1 week

### PHASE 2: Medium-Risk Routes (2-3 weeks)
**Extract:** Settings + Model/API + PPT routes
**Total:** ~600 lines
**Benefit:** app.py to ~16,800 lines, isolation of stateful operations
**Timeline:** 2 weeks
**Caution:** Test thoroughly - involves lazy loading and client switching

### PHASE 3: High-Risk Routes (3-4 weeks)
**Extract:** Chat routes
**Total:** ~4,000 lines
**Benefit:** app.py to ~12,800 lines, major refactoring benefit
**Timeline:** 3-4 weeks (requires memory_manager refactoring)
**Caution:** Most complex - circular risk via memory_manager

### PHASE 4: Infrastructure Consolidation (Ongoing)
**Create:**
- core/singletons.py - Manage session_manager, brain, settings_manager
- core/client_manager.py - Client creation and mode switching
- core/proxy_manager.py - Proxy detection logic
- helpers/system_instruction.py - Consolidate instruction functions

**Benefit:** Clear initialization order, easier testing

---

## 🛡️ SAFETY GUIDELINES FOR EXTRACTION

### DO ✅
1. **Use getter functions** for lazy-loaded globals
   `python
   from app import get_memory_manager()
   mem_mgr = get_memory_manager()  # ✅ Correct
   `

2. **Import singletons directly** (they're thread-safe)
   `python
   from app import session_manager, brain, settings_manager  # ✅ OK
   `

3. **Use Blueprint dependency injection**
   `python
   from flask import Blueprint
   bp = Blueprint('myroutes', __name__)
   
   @bp.route('/myroute')
   def handler():
       from app import session_manager  # ✅ Lazy import OK
   `

4. **Keep helpers stateless**
   - Utility functions should not maintain state
   - Should not import route handlers

5. **Use getter + atomic operations for mutable globals**
   `python
   def switch_model():
       client = get_client()  # ✅ Gets current/switches atomically
       # Use client
   `

### DON'T ❌
1. **Re-instantiate singletons in blueprints**
   `python
   session_manager = SessionManager()  # ❌ Creates duplicate
   `

2. **Import route functions from other blueprints**
   `python
   from app import chat  # ❌ Circular dependency
   `

3. **Access internal cache dicts directly**
   `python
   _user_settings_cache['key'] = value  # ❌ Use settings_manager
   `

4. **Assume lazy globals are initialized**
   `python
   _memory_manager.get_context()  # ❌ May be None, use getter
   `

5. **Create new threads for blueprint operations**
   `python
   threading.Thread(target=bp_function).start()  # ❌ Use task queue
   `

---

## 📊 IMPACT ANALYSIS

### Current State
- **Monolithic:** 17,836 lines in single file
- **Testing:** Hard to unit test individual route groups
- **Maintenance:** All 80+ routes entangled
- **Load time:** 100+ globals initialized at startup
- **Modification risk:** Changing one route may affect others

### After Full Extraction
- **Modular:** 9 route files + core modules
- **Testing:** Each route group testable in isolation
- **Maintenance:** Clear dependencies between files
- **Load time:** Lazy loading reduces startup
- **Modification risk:** Changes isolated to specific route group

### Performance Impact
- Startup time: Similar (lazy loading mitigates)
- Runtime: No change (same logic)
- Memory: Slightly lower (shared singletons)
- Import chains: Faster (module search optimized)

---

## 📁 GENERATED DOCUMENTATION

Three analysis documents have been created:

1. **DEPENDENCY_ANALYSIS.md** (Comprehensive)
   - Complete globals-to-routes mapping
   - Class dependency graph
   - Circular risk assessment
   - Detailed route analysis
   - ~400 lines

2. **EXTRACTION_SUMMARY.md** (Quick Reference)
   - Route group extraction difficulty (emoji ratings)
   - Which globals each group uses
   - Circular dependency check
   - File size breakdown estimate
   - ~300 lines

3. **TECHNICAL_REFERENCE.md** (Developer Guide)
   - Tier-based global categorization
   - Detailed route access patterns
   - Lazy loading functions reference
   - Safe vs. unsafe globals
   - ~350 lines

---

## ✅ NEXT STEPS

1. **Review** the three generated documents
2. **Prioritize** Phase 1 routes (SESSION, PAGE, WORKSPACE)
3. **Create tests** for each route group first
4. **Implement** extraction with Blueprint pattern
5. **Verify** imports work with getter functions
6. **Document** new module structure
7. **Deploy** incrementally, test after each phase

---

## 📞 KEY CONTACTS FOR QUESTIONS

**Memory Manager Complexity:** See get_memory_manager() (line 6082)
**Client Switching:** See get_client() (line 655) and _get_local_model_config() (line 633)
**Lazy Loading Pattern:** See _LazyModule class (line 77)
**Interrupt Management:** See StreamInterruptManager (line 272)
**Session Storage:** See SessionManager (line 5927)

---

**Analysis Date:** 2026-03-16 20:20:19
**Analyzer:** Code Exploration Agent
**Files Analyzed:** 1 (web/app.py)
