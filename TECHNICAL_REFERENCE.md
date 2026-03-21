# TECHNICAL REFERENCE: GLOBALS → ROUTES MATRIX

## Complete Dependency Map

### Module-Level Globals (100+ total) - Organized by Lifecycle

#### Tier 0: App Initialization (Must exist before any routes)
| Global | Type | Line | Initialized | Mutated | Risk |
|--------|------|------|---|---|---|
| app | Flask | 1454 | Once | Extensions only | None |
| _app_logger | Logger | 6 | Once | No | None |
| PROJECT_ROOT | str | 337 | Once | No | None |
| CHAT_DIR | str | 1945 | Once | No | None |
| WORKSPACE_DIR | str | 1946 | Lazy (get_workspace_root) | No | Low |
| UPLOAD_DIR | str | 1947 | Once | No | None |
| API_KEY | str | 358 | Once (from env) | No | None |

#### Tier 1: Singletons (Created once, shared globally)
| Global | Type | Line | Supplier | Users | Mutated |
|--------|------|------|----------|-------|---------|
| session_manager | SessionManager | 6074 | Direct init | chat, session routes | Yes (append_and_save) |
| brain | KotoBrain | 7046 | Direct init | chat routes, analyze | No |
| settings_manager | SettingsManager | 1957 | Direct init | settings routes, setup | Yes (save) |
| _model_manager | ModelManager | 2041 | _init_model_manager() | api routes | No |

#### Tier 2: Lazy-Loaded Globals (Created on first access)
| Global | Type | Line | Loader | First User | Cached |
|--------|------|------|--------|------------|--------|
| _client | OllamaClientProxy \| genai.Client | 651 | get_client() | chat, setup | Yes |
| _memory_manager | EnhancedMemoryManager | 6078 | get_memory_manager() | chat_stream | Yes |
| _kb | KnowledgeBase | 6079 | get_knowledge_base() | notes routes | Yes |
| _model_manager | ModelManager | 2041 | _init_model_manager() | api_info | Yes |
| _detected_proxy | str | 557 | get_detected_proxy() | client creation | Yes |

#### Tier 3: Infrastructure Caches (Management objects)
| Global | Type | Purpose | Mutated | Accessed by |
|--------|------|---------|---------|-------------|
| _user_settings_cache | dict | Settings JSON | Yes | settings routes |
| _document_workflow_cache | dict | Document executor | No | (lazy load) |
| _ppt_system_cache | dict | PPT modules | No | (lazy load) |
| _interrupt_manager | StreamInterruptManager | Per-session flags | Yes | chat_stream, interrupt routes |
| _blueprints_registered | bool | Registration flag | Yes | _register_blueprints_deferred() |

#### Tier 4: Constants & Configuration
| Global | Type | Line | Purpose | Immutable |
|--------|------|------|---------|-----------|
| MODEL_MAP | dict | 1980 | Task → model ID | Yes |
| MODEL_INFO | dict | 2100 | Model capabilities | Yes |
| PROXY_OPTIONS | list | 417 | Fallback proxies | Yes |
| TASK_PROMPTS | dict | 3358 | System prompts | Yes |
| WINDOWS_SHORTCUTS | dict | 3394 | OS shortcuts | Yes |
| _INTERACTIONS_ONLY_MODELS | set | 1998 | Interactions API models | Yes |
| _INTERACTIONS_AGENT_MODELS | frozenset | 2008 | Agent models | Yes |

---

## Route Groups: Detailed Globals Access Pattern

### CHAT ROUTES: /api/chat, /api/chat/stream, /api/chat/file, /api/chat/interrupt
**Location:** Lines 7210-13250
**Count:** 5 routes
**Total lines:** ~4,000

#### Globals Read (In order of dependency):
1. API_KEY (358) - Early check
2. session_manager (6074) - Load history
3. brain (7046) - AI response
4. MODEL_MAP (1980) - Task classification
5. _memory_manager (6078) - Context injection [chat_stream only]
6. _interrupt_manager (326) - Interrupt flags [chat_stream only]
7. CHAT_DIR (1945) - File path
8. WORKSPACE_DIR (1946) - File path

#### Globals Modified:
- session_manager (append_and_save) - User/model messages

#### Critical Helper Functions:
- Utils.sanitize_string() - Input validation
- ContextAnalyzer.filter_history() - Context optimization
- _get_system_instruction() - Instruction synthesis
- session_manager.load_full() - History retrieval
- brain.chat() - AI generation

**Extraction Risk:** 🔴 HIGH (circular risk via memory_manager)

---

### SESSION ROUTES: /api/sessions/*
**Location:** Lines 7105-7200
**Count:** 4 routes (GET list, POST create, GET detail, DELETE)
**Total lines:** ~95

#### Globals Read:
1. session_manager (6074) - All CRUD ops
2. CHAT_DIR (1945) - Directory listing

#### Globals Modified:
- session_manager (create, delete)

**Extraction Risk:** ✅ NONE (isolated dependencies)

---

### WORKSPACE ROUTES: /api/workspace/*
**Location:** Lines 15441-15535
**Count:** 4 routes
**Total lines:** ~95

#### Globals Read:
1. WORKSPACE_DIR (1946)
2. UPLOAD_DIR (1947)

#### Globals Modified: NONE

**Extraction Risk:** ✅ NONE (pure file I/O)

---

### SETTINGS ROUTES: /api/settings*, /api/local-model/*, /api/switch-to-*
**Location:** Lines 15658-15768
**Count:** 9 routes
**Total lines:** ~120

#### Globals Read:
1. settings_manager (1957) - All CRUD ops
2. _user_settings_cache (364) - Direct access
3. _user_settings_lock (365) - Thread safety
4. _client (651) - Read for model mode
5. _get_local_model_config() - Config check

#### Globals Modified:
- _user_settings_cache (direct dict write)
- _client (reassigned if model switches)

**Extraction Risk:** ⚠️ MEDIUM (_client is mutable)

---

### MODEL/API ROUTES: /api/info, /api/v1/models, /api/analyze
**Location:** Lines 15241-15441
**Count:** 4 routes
**Total lines:** ~200

#### Globals Read:
1. API_KEY (358) - Header check
2. MODEL_MAP (1980) - Model listing
3. MODEL_INFO (2100) - Metadata
4. _model_manager (2041) - Lazy init via _init_model_manager()
5. brain (7046) - analyze_task() call

#### Globals Modified: NONE

**Extraction Risk:** ⚠️ MEDIUM (lazy initialization dependency)

---

### PPT ROUTES: /api/ppt/download, /api/ppt/session
**Location:** Lines 15165-15241
**Count:** 2 main routes + blueprint routes (ppt_api_routes.py)
**Total lines:** ~150

#### Globals Read:
1. PPTMasterOrchestrator (258) - Lazy proxy
2. PPTGenerationPipeline (261) - Lazy proxy
3. session_manager (6074) - Load session
4. WORKSPACE_DIR (1946) - File path
5. UPLOAD_DIR (1947) - File path

#### Globals Modified:
- (None directly, but PPT creation modifies WORKSPACE_DIR files)

**Extraction Risk:** ⚠️ MEDIUM (lazy module loading)

---

### PAGE ROUTES: /, /app, /file-network, /knowledge-graph, /mini, /mobile
**Location:** Lines 7051-7102
**Count:** 9 routes
**Total lines:** ~50

#### Globals Read:
- None (template rendering only)

#### Globals Modified: NONE

**Extraction Risk:** ✅ NONE (pure rendering)

---

### SETUP ROUTES: /api/setup/*, /api/diagnose
**Location:** Lines 15973-16149
**Count:** 5 routes
**Total lines:** ~200

#### Globals Read:
1. API_KEY (358) - Status check
2. settings_manager (1957) - Setup state
3. get_client() - Test endpoint
4. PROJECT_ROOT (337) - System info

#### Globals Modified: NONE (setup_routes don't change config, only read/test)

**Extraction Risk:** ✅ NONE (read-only operations)

---

## Dependency Isolation Matrix

### Which Route Groups Can Be Extracted Together?

`
SESSION           ✅ Isolated
  └─ depends: session_manager

PAGE              ✅ Isolated
  └─ depends: nothing

WORKSPACE         ✅ Isolated
  └─ depends: WORKSPACE_DIR, UPLOAD_DIR

SETUP             ✅ Isolated
  └─ depends: API_KEY, settings_manager, get_client()

SETTINGS          ⚠️  Semi-isolated
  └─ depends: settings_manager, _client (mutable)

MODEL/API         ⚠️  Semi-isolated
  └─ depends: _model_manager (lazy), brain

PPT               ⚠️  Semi-isolated
  └─ depends: PPT lazy proxies, session_manager

CHAT              🔴 Tightly coupled
  └─ depends: brain, memory_manager, interrupt_manager, many helpers
  └─ circular risk: memory_manager → chat context
`

### Safe Extraction Combinations:

**Phase 1 (Bundle safely):**
- SESSION + PAGE + WORKSPACE + SETUP (no inter-dependencies)

**Phase 2 (Careful dependency injection):**
- SETTINGS (inject settings_manager)
- MODEL/API (inject _model_manager getter)
- PPT (inject lazy proxies)

**Phase 3 (Major refactor):**
- CHAT (refactor memory_manager, interrupt handling)

---

## Lazy Loading Functions (Getter Pattern)

These functions return cached instances:

`python
def get_memory_manager():
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = EnhancedMemoryManager()
    return _memory_manager

def get_knowledge_base():
    global _kb
    if _kb is None:
        _kb = KnowledgeBase()
    return _kb

def get_client():
    global _client, _client_mode_key
    current_key = (model_mode, local_model)
    if _client is None or _client_mode_key != current_key:
        # Switch between Ollama and Gemini
        _client = create_client()
    return _client

def get_detected_proxy():
    global _detected_proxy, _proxy_checked
    if not _proxy_checked:
        _detected_proxy = setup_proxy()
        _proxy_checked = True
    return _detected_proxy

def _init_model_manager():
    global _model_manager
    if _model_manager is None:
        _model_manager = ModelManager()
    return _model_manager
`

**Usage in extracted blueprints:**
`python
from app import get_memory_manager

def my_route():
    mem_mgr = get_memory_manager()  # ✅ Correct
    memory_manager = _memory_manager  # ❌ Wrong (import fails)
`

---

## Summary: Safe vs. Unsafe Globals for Extraction

### ✅ SAFE TO REFERENCE (Immutable)
- PROJECT_ROOT, CHAT_DIR, WORKSPACE_DIR, UPLOAD_DIR
- API_KEY
- MODEL_MAP, MODEL_INFO
- TASK_PROMPTS, WINDOWS_SHORTCUTS
- All singletons via getters (session_manager, brain, settings_manager)

### ⚠️ REQUIRES CARE (Mutable or lazy-loaded)
- _client (switches between Ollama/Gemini)
- _user_settings_cache (dict mutation)
- _model_manager (lazy initialization)
- Lazy proxies (PPT, document workflow)

### ❌ DO NOT ACCESS DIRECTLY (Internal infrastructure)
- _blueprints_registered, _blueprints_lock
- _proxy_checked, _detected_proxy
- _document_workflow_cache, _ppt_system_cache
- _interrupt_flags (use _interrupt_manager instead)

