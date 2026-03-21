# 📋 KOTO TEST SPECIFICATIONS - MASTER INDEX

Generated: 03/16/2026 02:44:30
Source File: C:\repos\Koto\web\app.py (17,000+ lines)
Focus: 5 Major Classes with Complete Method Documentation

---

## 📁 GENERATED DOCUMENTATION FILES:

### 1. **TEST_SPECIFICATIONS.md** (MAIN DOCUMENT - 5000+ lines)
   Complete reference for writing unit tests
   
   Contains:
   ✓ FileOperator (6 methods) - Lines 2198-2560
   ✓ WebSearcher (3 methods) - Lines 2563-2850
   ✓ ContextAnalyzer (3 methods) - Lines 3428-4022
   ✓ Utils (5 methods) - Lines 5471-5750
   ✓ SessionManager (7 methods) - Lines 5927-6072
   
   For Each Method:
   • Exact line number in source
   • Complete method signature
   • All parameters with types
   • Full logic flow with branches
   • Return value structure (exact dict/list keys)
   • 2-4 concrete test case examples
   • Side effects & special behaviors

### 2. **CODE_EXAMPLES.md** (ACTUAL SOURCE CODE)
   Real code snippets from app.py with line numbers
   
   Includes:
   • Actual @classmethod/@staticmethod signatures
   • Full method implementations
   • Test examples for each
   • Return value examples
   • Class constants definitions

### 3. **CODE_REFERENCE.txt** (QUICK LOOKUP)
   Fast reference with:
   • All class/method line numbers
   • Critical constants to mock
   • Imports to check
   • Testing considerations per class
   • What to mock/patch in tests

---

## 🎯 CLASS SUMMARIES:

### 1️⃣ FileOperator CLASS (Line 2198)
**Purpose:** Handle local file operations (read, write, organize, list)

Methods:
┌─ is_file_operation(text) → bool
│  └─ Detect file operation keywords
├─ _is_folder_organize_intent(text_lower) → bool
│  └─ Detect folder organization intent
├─ _extract_path_from_text(user_input) → str
│  └─ Extract file/folder paths (3 regex patterns)
├─ execute(user_input) → dict
│  └─ Main execution (5+ operation branches)
├─ get_file_metadata(filepath) → dict
│  └─ Get file stats (size, timestamps, extension)
└─ watch_directory(directory, callback, patterns) → dict
   └─ Monitor directory for file changes (watchdog)

**Key Testing Points:**
• Path regex patterns (quoted, Windows absolute, Unix relative)
• File size formatting (KB truncation at 1024 bytes)
• Content truncation at 10,000 characters
• Folder organize creates external orchestrator object
• Max 50 items in directory listing

---

### 2️⃣ WebSearcher CLASS (Line 2563)
**Purpose:** Detect when web search is needed and format queries

Methods:
┌─ needs_web_search(text) → bool
│  └─ Check if query needs web search (11 patterns + 50+ keywords)
├─ _detect_query_type(query) → str
│  └─ Classify query type (travel/weather/finance/general)
└─ _build_search_context(query, query_type) → tuple
   └─ Generate system instruction based on query type

**Key Testing Points:**
• 11 regex patterns checked BEFORE keyword list
• All patterns use re.IGNORECASE flag
• Travel patterns very specific (dates, routes, stations)
• Travel queries return Markdown table format (8 columns)
• Finance queries require price + daily% + trend
• Weather queries need 3-day forecast + advice

---

### 3️⃣ ContextAnalyzer CLASS (Line 3428)
**Purpose:** RAG-style context analysis for continuation detection

Methods:
┌─ extract_entities(text, task_type) → list
│  └─ Extract colors, styles, subjects, task-specific entities
├─ build_context_summary(history, max_turns) → dict
│  └─ Analyze history (3-turn window by default)
└─ analyze_context(user_input, history) → dict
   └─ RAG analysis with continuation detection

**Key Testing Points:**
• 5 task types with keywords: PAINTER, FILE_GEN, RESEARCH, CODER, CHAT
• 6 continuation patterns with weights: modify/reference/convert/continue/detail
• Continuation requires confidence > 0.5
• Input length limits prevent false continuations
• Task mismatch detection prevents cross-task continuations
• New topic indicators reduce weight by 80%
• Weight calculation: base × (1 + 0.1 × match_count)

---

### 4️⃣ Utils CLASS (Line 5471)
**Purpose:** Utility functions for string handling, validation, package detection

Methods:
┌─ sanitize_string(s) → str
│  └─ Clean UTF-8 encoding issues
├─ is_failure_output(text) → bool
│  └─ Detect failure indicators (26 phrases)
├─ detect_required_packages(text) → list
│  └─ Parse imports, return allowed packages (12-item allowlist)
├─ adapt_prompt_to_markdown(task_type, user_input, history) → str
│  └─ Convert to structured Markdown via PromptAdapter
└─ quick_self_check(task_type, user_input, output_text) → dict
   └─ Validate output using gemini-2.0-flash-lite (max 300 tokens)

**Key Testing Points:**
• 26 "no internet" phrases (English + Chinese)
• Package allowlist: numpy, PIL, cv2, sklearn, pandas, requests, etc.
• Import parsing handles both "import X" and "from X import Y"
• 12-item package allowlist (strict security)
• Model-based validation with temperature=0.1

---

### 5️⃣ SessionManager CLASS (Line 5927)
**Purpose:** Manage conversation session storage and retrieval

Methods:
┌─ list_sessions() → list
│  └─ List all sessions sorted by modification time (newest first)
├─ load(filename) → list
│  └─ Load history (trimmed to max 20 turns)
├─ load_full(filename) → list
│  └─ Load complete untruncated history
├─ create(name) → str
│  └─ Create new session (timestamp collision handling)
├─ save(filename, history) → None
│  └─ Write history to JSON
├─ delete(filename) → bool
│  └─ Delete session file
└─ Helper methods:
   ├─ append_and_save() - Append both messages atomically
   ├─ append_user_early() - Save user message immediately
   ├─ update_last_model_response() - Update last model entry
   └─ add_message() - Add single message with metadata

**Key Testing Points:**
• JSON file storage in CHAT_DIR with UTF-8
• Modification time sorting via os.path.getmtime()
• History trimming to 20 turns (prevents token overflow)
• Full history preserved on disk (trimming only for context)
• Session name sanitization (alphanumeric + underscores)
• Timestamp collision handling: append epoch time
• ensure_ascii=False preserves Chinese characters

---

## 📊 TESTING CHECKLIST:

### FileOperator
- [ ] Test path extraction with 3 regex patterns
- [ ] Test file reading with truncation (10K chars)
- [ ] Test directory listing (max 50 items)
- [ ] Test file metadata generation
- [ ] Test folder organize intent detection
- [ ] Mock watchdog for directory monitoring

### WebSearcher
- [ ] Test all 11 regex patterns
- [ ] Test keyword matching (50+ keywords)
- [ ] Test query type detection (4 types)
- [ ] Test context building per query type
- [ ] Test travel format (Markdown table)
- [ ] Test finance format (price + trend)

### ContextAnalyzer
- [ ] Test entity extraction (colors, styles, subjects)
- [ ] Test context summary building (3-turn window)
- [ ] Test continuation detection (6 pattern types)
- [ ] Test confidence scoring
- [ ] Test input length limits
- [ ] Test task type mismatch detection
- [ ] Test new topic indicator detection
- [ ] Test RAG prompt building

### Utils
- [ ] Test UTF-8 sanitization
- [ ] Test failure detection (empty, emoji, phrases)
- [ ] Test all 26 "no internet" phrases
- [ ] Test package detection (import parsing)
- [ ] Test package allowlist (12 items)
- [ ] Test prompt adaptation
- [ ] Mock gemini-2.0-flash-lite for self-check

### SessionManager
- [ ] Test list_sessions() sorting
- [ ] Test load() with history trimming (20 turns)
- [ ] Test create() with collision handling
- [ ] Test save/load roundtrip
- [ ] Test delete() with file checking
- [ ] Test append_and_save() atomicity
- [ ] Test JSON UTF-8 handling
- [ ] Mock os.path.getmtime()

---

## 🔑 CRITICAL MOCKS FOR TESTS:

Global Constants:
- CHAT_DIR: Mock with tempfile.mkdtemp()
- WORKSPACE_DIR: Mock with test path
- client: Mock Gemini API
- _app_logger: Mock logger

Imports to Patch:
- watchdog.observers.Observer
- os.path.exists, os.path.isdir, os.stat
- json.load, json.dump
- re.search, re.match
- importlib.util.find_spec
- open() for file operations

External Classes:
- FolderCatalogOrganizer: Mock folder organize operation
- PromptAdapter: Mock prompt conversion
- FileSystemEventHandler: Mock watchdog handler

---

## 💡 QUICK START FOR WRITERS:

1. Read **TEST_SPECIFICATIONS.md** for complete method behavior
2. Check **CODE_EXAMPLES.md** for actual source code
3. Use **CODE_REFERENCE.txt** for quick line number lookup
4. Write tests based on test case examples provided
5. Mock all external dependencies per section above

Each method has:
✓ Exact line number
✓ Full logic description
✓ Return structure with exact keys
✓ Multiple test case examples
✓ Edge cases & special behaviors

You have everything needed to write comprehensive unit tests!

