# C:\repos\Koto\web\app.py - Dependency Analysis

## 1. FLASK APP CREATION & CONFIGURATION

### App Creation (Line 1454)
pp = Flask(__name__)

### Configuration

**Config Properties:**
- pp.config["SEND_FILE_MAX_AGE_DEFAULT"] = 3600 (static asset caching)
- pp.config["MAX_CONTENT_LENGTH"] = 20MB (request body limit)

**Registered Middleware/Extensions:**

| Extension | Registration | Purpose |
|-----------|--------------|---------|
| CORS | CORS(app, origins=_cors_origins) | Cross-origin support |
| Sentry | sentry_sdk.init(...) | Error tracking (optional) |
| Prometheus | PrometheusMetrics(app) | Metrics at /metrics |
| Swagger | Swagger(app, config, template) | API docs at /apidocs/ |
| Flask-Sock | Sock(app) | WebSocket support (optional) |

**Request Handlers:**
- @app.before_request -> _assign_request_id() [Line 1559]
- @app.after_request -> _attach_request_id() [Line 1565]
- @app.errorhandler(404/405/500) [Lines 1584-1599]

**Blueprints Registered (Lines 1651-1843):**
- health_bp, task_bp, agent_bp, skill_bp, marketplace_bp
- distill_bp (if KOTO_DEV_TRAINING=1), voice_bp, ppt_api_bp
- goal_bp, file_hub_bp, job_bp, ops_bp, shadow_bp, macro_bp

---

## 2. MODULE-LEVEL GLOBALS BY ROUTE GROUP

### CORE CONFIGURATION (Used by ALL/MOST routes)
- API_KEY (358) - Gemini API key
- PROJECT_ROOT (337) - App root directory
- CHAT_DIR (1945) - Chat history storage
- WORKSPACE_DIR (1946) - User workspace
- UPLOAD_DIR (1947) - Upload temp directory
- settings_manager (1957) - SettingsManager singleton
- session_manager (6074) - SessionManager singleton
- brain (7046) - KotoBrain singleton

### CHAT/MEMORY GLOBALS (Used by chat_stream, chat, analyze_task)
- _memory_manager (6078) - Long-term memory (lazy)
- _kb (6079) - Knowledge base (lazy)
- _interrupt_manager (326) - Stream interrupt flags
- MODEL_MAP (1980) - Task -> model ID mapping
- MODEL_INFO (2100) - Model metadata

### CLIENT/MODEL GLOBALS (Used by chat, api_info, local_model_switch)
- _client (651) - AI client (lazy, switches between Ollama/Gemini)
- _client_mode_key (652) - Cache key for client mode
- _model_manager (2041) - Model configuration (lazy)
- client (978) - Tracked client proxy

### PROXY/NETWORK GLOBALS (Used by client creation, setup routes)
- _detected_proxy (557) - System proxy (lazy)
- _proxy_checked (558) - Proxy detection flag
- PROXY_OPTIONS (417) - Fallback proxies

### LAZY-LOADED MODULES (Used by various routes)
- genai (125) - google.genai library (_LazyModule)
- types (126) - google.genai.types (_LazyModule)
- requests (127) - requests library (_LazyModule)
- DocumentWorkflowExecutor (171) - Document workflow (_DocWorkflowProxy)
- PPTMasterOrchestrator (258) - PPT generation (_PPTModuleProxy)

### INFRASTRUCTURE GLOBALS
- app (1454) - Flask application
- sock (1622) - WebSocket handler
- _blueprints_registered (1647) - Blueprint registration flag
- PARALLEL_SYSTEM_ENABLED (63) - Parallel execution available

---

## 3. ROUTE GROUPS & THEIR GLOBALS

### CHAT ROUTES (7210-13250)
Routes: POST /api/chat, /api/chat/stream, /api/chat/file, /api/chat/interrupt

**Reads globals:**
- session_manager.load_full(), append_and_save()
- brain.chat()
- MODEL_MAP, MODEL_INFO
- API_KEY
- _memory_manager.get_context_string() [chat_stream]
- _interrupt_manager.set_interrupt(), is_interrupted() [chat_stream]
- CHAT_DIR, WORKSPACE_DIR
- _get_system_instruction(), _get_DEFAULT_CHAT_SYSTEM_INSTRUCTION()

**Helper functions:**
- Utils.sanitize_string()
- ContextAnalyzer.filter_history()
- TaskOrchestrator.execute_compound_task()
- FileOperator methods (for chat_with_file)
- LocalDispatcher (for simple query detection)

---

### SESSION ROUTES (7105-7200)
Routes: GET /api/sessions, POST /api/sessions, GET /api/sessions/<name>, DELETE /api/sessions/<name>

**Reads globals:**
- session_manager (all session ops)
- CHAT_DIR

**Helper functions:**
- SessionManager.load_full(), load(), load_brief()
- SessionManager.save(), delete()

---

### WORKSPACE ROUTES (15441-15535)
Routes: GET /api/workspace/<path>, GET /api/workspace, POST /api/open-workspace, POST /api/open-file

**Reads globals:**
- WORKSPACE_DIR
- UPLOAD_DIR
- FileOperator

**Helper functions:**
- FileOperator.list_files(), get_file()
- os.path operations

---

### SETTINGS ROUTES (15658-15768)
Routes: GET/POST /api/settings, /api/settings/reset, /api/switch-to-mini, /api/switch-to-main, /api/local-model/*

**Reads globals:**
- settings_manager
- _user_settings_cache, _user_settings_lock
- _client (for model switching)
- _get_local_model_config()
- get_client()
- PROJECT_ROOT

**Helper functions:**
- _load_user_settings()
- setup_proxy()
- get_detected_proxy()

---

### MODEL/API ROUTES (15241-15441)
Routes: GET /api/info, GET /api/v1/models, POST /api/v1/models/refresh, POST /api/analyze

**Reads globals:**
- API_KEY
- MODEL_MAP
- MODEL_INFO
- _model_manager (lazy init via _init_model_manager())
- brain.analyze_task()

**Helper functions:**
- _init_model_manager()
- get_model_display_name()

---

### PPT ROUTES (15165-15241)
Routes: POST /api/ppt/download, GET /api/ppt/session/<id>

**Reads globals:**
- PPTMasterOrchestrator
- PPTGenerationPipeline
- session_manager
- WORKSPACE_DIR
- UPLOAD_DIR

**Helper functions:**
- get_ppt_system()

---

### PAGE ROUTES (7051-7102)
Routes: GET /, /app, /file-network, /knowledge-graph, /test_upload, /edit-ppt/<id>, /skills, /mini, /m, /mobile

**Reads globals:**
- PROJECT_ROOT (for template paths)
- None (mostly static rendering)

---

### VOICE ROUTES (16620-16775+)
Implemented via voice_bp blueprint (registered at line 1748)

**Routes:** GET /api/voice/engines, POST /api/voice/record, etc.

**Note:** Registered from voice_api_enhanced module

---

### SETUP/DIAGNOSE ROUTES (15973-16149)
Routes: GET /api/setup/status, POST /api/setup/apikey, /api/setup/workspace, /api/setup/test, GET /api/diagnose

**Reads globals:**
- API_KEY
- settings_manager
- get_client() (for test)
- PROJECT_ROOT

---

## 4. CLASS DEPENDENCIES

### Core Classes
- FileOperator (2198) - File I/O, reads WORKSPACE_DIR, UPLOAD_DIR
- WebSearcher (2563) - Search, reads client
- ContextAnalyzer (3428) - Context extraction, reads MODEL_MAP
- TaskOrchestrator (4087) - Multi-task execution, reads TaskOrchestrator (recursive)
- LocalDispatcher (5447) - Task classification, reads LOCAL_ROUTER_MODEL
- Utils (5471) - Utility functions (static), reads nothing
- SessionManager (5927) - Chat session storage, reads CHAT_DIR
- KotoBrain (6316) - Main AI engine, reads _model_manager, MODEL_MAP, session_manager
- StreamInterruptManager (272) - Interrupt flags, no globals
- _ClientProxy (968) - Client wrapper, reads _client
- _TrackedModels (764) - Token tracking, reads client
- _LazyModule (77) - Generic lazy loader

### Class-to-Class Calls
`
KotoBrain.chat()
├─ calls ContextAnalyzer methods
├─ calls TaskOrchestrator.execute_compound_task()
├─ calls FileOperator methods
└─ reads MODEL_MAP, session_manager, _model_manager

chat_stream()
├─ calls ContextAnalyzer.filter_history()
├─ calls KotoBrain.chat()
├─ calls session_manager.append_and_save()
└─ reads _memory_manager, _interrupt_manager
`

---

## 5. CIRCULAR DEPENDENCY RISKS

### MODERATE RISK: chat_stream → memory_manager → knowledge_graph
Pattern: chat_stream() calls _memory_manager.get_context_string() which may call back into ContextAnalyzer or session context.

Mitigation: Ensure memory extraction is read-only. Don't call chat routes from memory_manager.

### LOW RISK: Blueprint registration → deferred loading
Pattern: Blueprints registered deferred at line 1651 may import app.py during their __init__.

Mitigation: Blueprints should use getter functions (get_memory_manager(), etc.) not direct globals.

### NO RISK: Helpers → routes (one-way)
Pattern: chat_stream() calls Utils.sanitize_string() but Utils never calls routes back.

---

## 6. SAFE EXTRACTION: ROUTE GROUPS TO SEPARATE FILES

### GROUP A: INDEPENDENT (Safe to extract immediately)
✅ Session routes (7105-7200) - Only needs session_manager, CHAT_DIR
✅ Page routes (7051-7102) - Only template rendering
✅ Workspace routes (15441-15535) - Only FileOperator, WORKSPACE_DIR

### GROUP B: INTERMEDIATE (Extract with dependency injection)
⚠️ Settings routes (15658-15768) - Needs settings_manager, careful with _client
⚠️ Model/API routes (15241-15441) - Needs _model_manager (lazy), MODEL_MAP
⚠️ PPT routes (15165-15241) - Needs PPTMasterOrchestrator (lazy), session_manager

### GROUP C: KEEP IN app.py (Core initialization)
❌ Chat routes (7210-13250) - Deep integration with brain, memory_manager
❌ Blueprint registration (1651-1843) - Controls app startup
❌ Client/Model init (651-684) - Lazy loading, mode switching
❌ Proxy setup (506-577) - Background thread, system detection

---

## 7. COMPLETE GLOBALS → ROUTES USAGE TABLE

| Route Group | session_manager | brain | MODEL_MAP | _memory_manager | _interrupt_manager | settings_manager | WORKSPACE_DIR | API_KEY |
|-------------|---|---|---|---|---|---|---|---|
| CHAT | ✓ | ✓ | ✓ | ✓ | ✓ | | | ✓ |
| SESSION | ✓ | | | | | | | |
| WORKSPACE | | | | | | | ✓ | |
| SETTINGS | | | | | | ✓ | | |
| MODEL/API | | ✓ | ✓ | | | | | ✓ |
| PPT | ✓ | | | | | | ✓ | |
| PAGE | | | | | | | | |
| VOICE | | | | | | | | |
| SETUP | | | | | | ✓ | | ✓ |

---

## 8. HELPER FUNCTIONS → ROUTE USAGE

| Helper Function | Defined | Used by Routes | Called by Classes |
|---|---|---|---|
| Utils.sanitize_string() | 5471 | ALL chat routes | ContextAnalyzer |
| ContextAnalyzer.* | 3428 | chat_stream | KotoBrain, TaskOrchestrator |
| _get_system_instruction() | 3221 | chat_stream | brain.chat() |
| session_manager.load_full() | 5927 | chat, chat_stream, get_session | brain |
| session_manager.append_and_save() | 5927 | chat, chat_stream | brain |
| FileOperator.* | 2198 | chat_with_file, workspace routes | TaskOrchestrator, KotoBrain |
| run_with_timeout() | 1305 | chat_stream | TaskOrchestrator |
| get_memory_manager() | 6082 | chat_stream | (supplier function) |
| get_knowledge_base() | 6296 | notes routes | (supplier function) |

---

## 9. RECOMMENDED SAFE EXTRACTION PLAN

**Priority 1 (Extract first):**
1. Session routes → routes/session_routes.py
2. Page routes → routes/page_routes.py
3. Workspace routes → routes/workspace_routes.py

**Priority 2 (Extract with careful dependency passing):**
1. Settings routes → routes/settings_routes.py
2. Model/API routes → routes/model_routes.py
3. Setup routes → routes/setup_routes.py

**Priority 3 (Requires full refactor):**
1. Chat routes → routes/chat_routes.py (needs brain, memory_manager injected)
2. PPT routes → routes/ppt_routes.py (needs PPT system injected)

**Keep in app.py:**
1. Blueprint registration system
2. Client/model initialization (lazy loading)
3. Proxy detection & setup
4. App configuration & middleware

