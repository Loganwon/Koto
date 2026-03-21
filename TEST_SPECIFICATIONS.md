# COMPREHENSIVE TEST SPECIFICATIONS FOR C:\repos\Koto\web\app.py

## 1. FileOperator CLASS (Line 2198)

### Class-Level Constants:
- FILE_KEYWORDS: List of 35+ keywords for file operations (Chinese & English)
- FOLDER_ORGANIZE_KEYWORDS: List of folder organization keywords

### Method: is_file_operation(cls, text) → bool
- **Location**: Line 2252
- **Signature**: @classmethod
- **Input**: text (string)
- **Logic**: 
  - Converts text to lowercase
  - Returns True if ANY keyword from FILE_KEYWORDS exists in text
- **Returns**: Boolean (True if file operation detected, False otherwise)
- **Test Case Examples**:
  - Input: "请读取文件 readme.txt" → True
  - Input: "你好吗" → False
  - Input: "open file data.csv" → True

### Method: _is_folder_organize_intent(cls, text_lower: str) → bool
- **Location**: Line 2258
- **Signature**: @classmethod
- **Input**: text_lower (lowercase string, MUST be pre-lowercased)
- **Logic**:
  - has_action: Check for ["归纳", "整理", "归档", "归类", "分类"] keywords
  - has_target: Check for ["文件夹", "目录", "路径", "文件"] keywords
  - Return True if BOTH has_action AND has_target exist
  - Also return True if ANY keyword from FOLDER_ORGANIZE_KEYWORDS exists
- **Returns**: Boolean
- **Test Cases**:
  - Input: "整理文件夹" → True (has both action + target)
  - Input: "整理" → True (matches FOLDER_ORGANIZE_KEYWORDS)
  - Input: "删除文件" → False (no organize keywords)

### Method: _extract_path_from_text(cls, user_input: str) → str
- **Location**: Line 2268
- **Signature**: @classmethod
- **Input**: user_input (raw user input)
- **Logic**:
  - Uses 3 regex patterns in order:
    1. r'["\']([^"\']+)["\']' - Quoted paths (single or double quotes)
    2. r'([A-Za-z]:\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\\/:*?"<>|\r\n]*)' - Windows absolute paths
    3. r"(\.?/[\w\-./ ]+)" - Unix-style paths
  - Returns first match from first pattern that succeeds
  - Strips whitespace and Chinese punctuation (，。,.;；) from result
- **Returns**: String (path or empty string if not found)
- **Test Cases**:
  - Input: 'Please organize "/home/user/downloads"' → "/home/user/downloads"
  - Input: '"C:\\Users\\Documents"' → "C:\Users\Documents"
  - Input: "随便删除文件" → ""

### Method: execute(cls, user_input) → dict
- **Location**: Line 2286
- **Signature**: @classmethod
- **Input**: user_input (string)
- **Logic**: 
  1. Converts input to lowercase
  2. Initializes result dict with: {"success": False, "action": "", "message": "", "content": ""}
  3. **FOLDER ORGANIZE PATH**: 
     - Calls _is_folder_organize_intent()
     - Extracts path via _extract_path_from_text()
     - Falls back to get_default_wechat_files_dir() if no path
     - Validates path exists and is directory
     - Creates FolderCatalogOrganizer and calls organize_folder()
     - Returns: success=True/False, action="folder_auto_catalog", message with stats, content empty
  4. **READ FILE PATH**:
     - Checks for ["读取", "打开文件", "查看文件", "读文件", "看看", "read file", "open file"]
     - Extracts file path with regex patterns
     - Reads file content (max 10000 chars, truncates with "...(文件过长，已截断)")
     - Returns: success=True/False, action="read_file", content wrapped in `
  5. **LIST FILES PATH**:
     - Checks for ["文件列表", "目录", "列出文件", "list files", "directory", "文件夹里"]
     - Extracts directory path
     - Lists up to 50 items with sizes (📁 for folders, 📄 for files)
     - Returns: success=True/False, action="list_files"
  6. **CREATE/WRITE FILE PATH**:
     - Returns message suggesting code generation feature
  7. **DEFAULT**:
     - Returns unrecognized operation message
- **Returns**: Dictionary with keys: success (bool), action (str), message (str), content (str)

### Method: get_file_metadata(cls, filepath) → dict
- **Location**: Line 2535
- **Signature**: @classmethod
- **Input**: filepath (string)
- **Logic**:
  - Checks if file exists (returns error dict if not)
  - Uses os.stat() to get file statistics
  - Formats timestamps to "YYYY-MM-DD HH:MM:SS"
  - Calculates size in KB
- **Returns**: Dictionary with keys:
  - success (bool)
  - filepath, filename, size, created, modified, extension, is_file (if success=True)
  - message (if success=False)
- **Test Cases**:
  - Valid file → Returns all metadata with size formatted
  - Nonexistent file → success=False, message="文件不存在"

### Method: watch_directory(cls, directory, callback=None, patterns=None) → dict
- **Location**: Line 2498
- **Signature**: @classmethod
- **Input**: 
  - directory (string path)
  - callback (optional function)
  - patterns (optional list, defaults to ["*.txt", "*.pdf", "*.docx", "*.xlsx", "*.csv"])
- **Logic**:
  - Uses watchdog library (FileSystemEventHandler, Observer)
  - Creates ChangeHandler that monitors for 'created' and 'modified' events
  - Filters by file extension patterns
  - Calls callback(event_type, file_path) when matching files change
  - Starts observer in recursive mode
- **Returns**: Dictionary with keys:
  - success (bool)
  - observer (watchdog.Observer instance if successful)
  - message (status or error message)
- **Side Effects**: Starts background file system observer

---

## 2. WebSearcher CLASS (Line 2563)

### Class-Level Constants:
- WEB_KEYWORDS: 50+ keywords for web search detection (weather, finance, travel, news)

### Method: needs_web_search(cls, text) → bool
- **Location**: Line 2626
- **Signature**: @classmethod
- **Input**: text (string)
- **Logic**:
  1. Converts to lowercase
  2. Checks 11 regex patterns (must_search_patterns) with case-insensitive flag:
     - Stock buying advice patterns
     - Real-time market/data patterns
     - Trend prediction patterns
     - Financial report patterns
     - New product/release patterns
     - Urgent/breaking news patterns
     - Gold price patterns
     - Transportation/ticket patterns (very detailed regex for dates, routes, stations)
     - Departure time queries
  3. If any pattern matches, returns True immediately
  4. Otherwise checks if ANY keyword from WEB_KEYWORDS exists
  5. Returns False if nothing matches
- **Returns**: Boolean
- **Test Cases**:
  - "今天天气怎么样" → True (weather keyword)
  - "比特币价格是多少" → True (finance keyword)
  - "明天从北京到上海的高铁票" → True (travel pattern)
  - "你好" → False

### Method: _detect_query_type(cls, query: str) → str
- **Location**: Line 2666
- **Signature**: @classmethod
- **Input**: query (string)
- **Logic**:
  - Converts to lowercase
  - Checks for travel keywords (火车票, 高铁, 航班, etc.) → returns "travel"
  - Checks for weather keywords (天气, 气温, 下雨, weather, forecast) → returns "weather"
  - Checks for finance keywords (股价, 股票, 黄金, 金价, 汇率, 比特币) → returns "finance"
  - Default: returns "general"
- **Returns**: String enum: "travel", "weather", "finance", "general"
- **Test Cases**:
  - "高铁票查询" → "travel"
  - "明天天气" → "weather"
  - "股票行情" → "finance"
  - "如何学习" → "general"

### Method: _build_search_context(cls, query: str, query_type: str) → tuple
- **Location**: Line 2721
- **Signature**: @classmethod
- **Input**: 
  - query (string)
  - query_type (string: "travel", "weather", "finance", "general")
- **Logic**:
  - If query_type == "travel": Returns (query, detailed instruction about trains/flights format)
    - Requires Markdown table with columns: 班次, 出发站, 到达站, 出发时间, 到达时间, 历时, 二等座, 一等座
    - Warns against fabricating missing data
  - If query_type == "weather": Returns (query, instruction for weather format)
    - Requires: current temp, high/low, 3-day forecast, travel advice
  - If query_type == "finance": Returns (query, instruction for finance format)
    - Requires: current price, daily change%, brief trend analysis
  - Default: Returns (query, generic instruction)
- **Returns**: Tuple of (enriched_query: str, system_instruction: str)
- **Test Cases**:
  - Query="高铁", Type="travel" → Returns instruction with table format
  - Query="天气", Type="weather" → Returns instruction with weather details

---

## 3. ContextAnalyzer CLASS (Line 3428)

### Class-Level Constants:
- TASK_SIGNATURES: Dictionary with signature patterns for 5 task types
  - "PAINTER": Image-related keywords, output patterns, entities
  - "FILE_GEN": Document-related keywords, file extensions, format entities
  - "RESEARCH": Analysis keywords, headers, entities like "定义", "特点"
  - "CODER": Code keywords, syntax patterns, entities
  - "CHAT": Generic keywords, no special outputs/entities

- CONTINUATION_PATTERNS: 6 pattern types with:
  - indicators (list of phrases)
  - weight (0.0-1.0, confidence)
  - max_input_length (optional, limits continuation detection)
  - require_start (optional, must appear at sentence start)
  - prompt_template (format string for injection)

### Method: extract_entities(cls, text: str, task_type: str = None) → list
- **Location**: Line 3650
- **Signature**: @classmethod
- **Input**: 
  - text (string to analyze)
  - task_type (optional: "PAINTER", "FILE_GEN", "CODER", "RESEARCH", "CHAT")
- **Logic**:
  - Checks for color keywords (红色, 蓝色, 绿色, 黄色, etc.) → Adds {"type": "color", "value": ...}
  - Checks for style keywords (可爱, 帅气, 写实, 卡通, etc.) → Adds {"type": "style", "value": ...}
  - Checks for subject keywords (猫, 狗, 人, 风景, etc.) → Adds {"type": "subject", "value": ...}
  - If task_type provided and in TASK_SIGNATURES:
    - Checks task-specific entities → Adds {"type": "task_specific", "value": ...}
- **Returns**: List of dicts [{"type": str, "value": str}, ...]
- **Test Cases**:
  - Input: "红色卡通的猫", task_type="PAINTER" → Returns color, style, subject, task_specific entities

### Method: build_context_summary(cls, history: list, max_turns: int = 3) → dict
- **Location**: Line 3718
- **Signature**: @classmethod
- **Input**: 
  - history (list of conversation turns: [{"role": "user"/"model", "parts": [str], ...}, ...])
  - max_turns (int, default 3, max recent turns to analyze)
- **Logic**:
  1. Initializes summary dict with keys: task_history, key_entities, last_user_intent, last_model_output, conversation_topic
  2. Takes last (max_turns * 2) turns from history
  3. For each turn:
     - If role=="user": Stores as last_user_intent, detects task type via TASK_SIGNATURES keywords
     - If role=="model": Stores as last_model_output
  4. Extracts entities from all user turns
  5. Deduplicates entities (by type:value)
  6. Sets conversation_topic to most recent task type detected
- **Returns**: Dictionary with structure shown above
- **Test Cases**:
  - History with image request → task_history contains PAINTER, entities include colors/styles
  - History with code request → task_history contains CODER

### Method: analyze_context(cls, user_input: str, history: list) → dict
- **Location**: Line 3855
- **Signature**: @classmethod
- **Input**:
  - user_input (current user input)
  - history (conversation history)
- **Logic**:
  1. Returns False for continuation if history < 2 turns
  2. Builds context summary via build_context_summary()
  3. Detects continuation type by checking CONTINUATION_PATTERNS:
     - For each pattern, counts indicator matches in user_input
     - Applies max_input_length filter if defined
     - Applies require_start check if defined (match must be in first 10 chars)
     - Calculates adjusted weight: weight * (1 + 0.1 * (matches - 1))
     - Selects pattern with highest weight if weight > 0.5
  4. Checks for new topic indicators (关于, 一篇, 帮我写, etc.) → reduces weight by 80%
  5. Checks for task type mismatch between previous and current → clears weight
  6. If weight > 0.5: Sets is_continuation=True, builds RAG enhanced prompt
  7. Special case: Checks for convert patterns regardless of weight
- **Returns**: Dictionary with keys:
  - is_continuation (bool)
  - related_task (str or None)
  - continuation_type (str or None: "modify", "reference", "convert", "continue", "detail")
  - context_summary (dict)
  - enhanced_input (str, RAG-enhanced user input)
  - confidence (float, 0.0-1.0)
- **Test Cases**:
  - History: [user: "生成图片：红色的猫", model: "已生成"], Input: "再来一张" → is_continuation=True, type="modify", confidence=0.9
  - Input: "帮我写一篇关于人工智能的文章" → is_continuation=False (new topic)

---

## 4. Utils CLASS (Line 5471)

### Class-Level Constants:
- _PACKAGE_ALLOWLIST: Dictionary mapping module names to pip package names
  - "pygame"→"pygame", "numpy"→"numpy", "cv2"→"opencv-python", "PIL"→"Pillow", etc.

### Method: sanitize_string(s) → str or original
- **Location**: Line 5495
- **Signature**: @staticmethod
- **Input**: s (any type)
- **Logic**:
  - If s is string: Encodes to UTF-8 with 'ignore' error handling, decodes back
  - Otherwise: Returns s unchanged
- **Returns**: Sanitized string or original value
- **Purpose**: Remove invalid UTF-8 sequences
- **Test Cases**:
  - Input: "hello" → "hello"
  - Input: "你好" → "你好"
  - Input: 123 → 123

### Method: is_failure_output(text: str) → bool
- **Location**: Line 5501
- **Signature**: @staticmethod
- **Input**: text (string)
- **Logic**:
  1. Returns True if text is empty or whitespace-only
  2. Converts to lowercase and trims
  3. Returns True if starts with "❌" OR contains "失败" or "错误"
  4. Checks for 26 "no internet" phrases (Chinese & English):
     - "没有直接联网", "无法联网", "i don't have access to the internet", etc.
  5. Returns True if ANY no-internet phrase found
  6. Otherwise returns False
- **Returns**: Boolean (True if output indicates failure)
- **Test Cases**:
  - Input: "" → True
  - Input: "❌ 操作失败" → True
  - Input: "无法联网，无法查询" → True
  - Input: "✅ 成功完成" → False

### Method: detect_required_packages(text: str) → list
- **Location**: Line 5616
- **Signature**: @staticmethod
- **Input**: text (code or output string)
- **Logic**:
  1. Returns [] if text is empty
  2. Parses import statements:
     - Finds lines starting with "import " → extracts module names (before comma or space)
     - Finds lines starting with "from " → extracts second word as module name
  3. Matches extracted modules against _PACKAGE_ALLOWLIST keys
  4. Converts to canonical pip package names
  5. Returns sorted list of unique packages
- **Returns**: Sorted list of package names (str)
- **Test Cases**:
  - Input: "import numpy\nimport cv2" → ["numpy", "opencv-python"]
  - Input: "from PIL import Image" → ["Pillow"]
  - Input: "import os" (not in allowlist) → []

### Method: adapt_prompt_to_markdown(task_type: str, user_input: str, history: list = None) → str
- **Location**: Line 5553
- **Signature**: @staticmethod
- **Input**:
  - task_type (task type identifier)
  - user_input (original user request)
  - history (optional conversation history)
- **Logic**:
  1. Imports PromptAdapter (from web.prompt_adapter or prompt_adapter)
  2. Calls PromptAdapter.adapt() with model_generate=None (local template only, no extra LLM call)
  3. Returns PromptAdapter output (Markdown formatted prompt)
  4. On exception: logs debug message and returns original user_input
- **Returns**: String (Markdown formatted prompt or original input on error)
- **Purpose**: Convert raw user request to structured Markdown for better LLM understanding
- **Test Cases**:
  - Input: task_type="CODER", user_input="写一个排序函数" → Returns Markdown with code template structure

### Method: quick_self_check(task_type: str, user_input: str, output_text: str) → dict
- **Location**: Line 5579
- **Signature**: @staticmethod
- **Input**:
  - task_type (task type)
  - user_input (original user request)
  - output_text (model output to validate)
- **Logic**:
  1. Creates check_prompt with instructions to validate output against requirements
  2. Calls gemini-2.0-flash-lite model with max_output_tokens=300, temperature=0.1
  3. Expects response: "PASS" OR "FAIL\nFIX_PROMPT: <suggestion>"
  4. Parses response:
     - If starts with "PASS": Returns {"pass": True, "fix_prompt": ""}
     - If starts with "FAIL": Extracts FIX_PROMPT line → Returns {"pass": False, "fix_prompt": "..."}
     - Otherwise: Returns {"pass": True, "fix_prompt": ""}
  5. On exception: Returns {"pass": True, "fix_prompt": ""}
- **Returns**: Dictionary with keys:
  - pass (bool)
  - fix_prompt (str, empty if pass=True)
- **Purpose**: Use fast model to validate if output meets user requirements

---

## 5. SessionManager CLASS (Line 5927)

### Constructor:
- **Location**: Line 5928
- **Initializes**: self.sessions = {} (in-memory session cache)

### Method: list_sessions(cls) → list
- **Location**: Line 5931
- **Signature**: Instance method
- **Logic**:
  1. Lists all .json files in CHAT_DIR
  2. Gets modification time for each file via os.path.getmtime()
  3. Sorts by mtime descending (newest first)
  4. Returns list of filenames sorted by recency
- **Returns**: List of filenames (strings) in order from newest to oldest
- **Test Cases**:
  - Empty CHAT_DIR → []
  - 3 sessions with different timestamps → ["newest.json", "middle.json", "oldest.json"]

### Method: load(self, filename) → list
- **Location**: Line 5943
- **Signature**: Instance method
- **Input**: filename (string)
- **Logic**:
  1. Constructs path: os.path.join(CHAT_DIR, filename)
  2. Checks if file exists
  3. Opens with UTF-8 encoding, errors='ignore'
  4. Loads full history from JSON
  5. Calls _trim_history() to truncate to last 20 turns (model context optimization)
  6. Returns trimmed history
  7. On error (JSONDecodeError, OSError): Logs warning and returns []
- **Returns**: List of history items (trimmed to ~20 turns max)
- **Side Effect**: Does NOT modify file; only truncates for context

### Method: load_full(self, filename) → list
- **Location**: Line 5957
- **Signature**: Instance method
- **Input**: filename (string)
- **Logic**:
  1. Similar to load() but returns COMPLETE history without trimming
  2. Used when appending to preserve full conversation log
- **Returns**: Full list of all history items or [] if error/not found

### Method: _trim_history(self, history, max_turns=20) → list
- **Location**: Line 5969
- **Signature**: Instance method, private
- **Input**:
  - history (list)
  - max_turns (int, default 20)
- **Logic**:
  1. If len(history) <= max_turns: returns unchanged
  2. Otherwise: returns last max_turns items (history[-max_turns:])
  3. Logs debug message with trim details
- **Returns**: Trimmed list (max 20 turns for context window management)

### Method: create(self, name) → str
- **Location**: Line 5978
- **Signature**: Instance method
- **Input**: name (string, user-provided session name)
- **Logic**:
  1. Sanitizes name: keeps only alphanumeric, replaces others with "_"
  2. Creates filename: "{sanitized_name}.json"
  3. Checks if file already exists
  4. If exists: Appends Unix timestamp to avoid overwriting: "{sanitized_name}_{timestamp}.json"
  5. Creates file with empty JSON array: []
- **Returns**: Filename (string) of newly created session
- **Side Effects**: Creates new .json file in CHAT_DIR
- **Test Cases**:
  - name="My Session" → filename="My_Session.json"
  - name already exists → filename="My_Session_{timestamp}.json"

### Method: save(self, filename, history) → None
- **Location**: Line 5990
- **Signature**: Instance method
- **Input**:
  - filename (string)
  - history (list of conversation items)
- **Logic**:
  1. Constructs path: os.path.join(CHAT_DIR, filename)
  2. Opens file with UTF-8 encoding, write mode
  3. Writes history as JSON with indent=2, ensure_ascii=False (preserves Unicode)
- **Returns**: None
- **Side Effects**: Overwrites/creates file with history
- **Test Cases**:
  - history=[] → File contains "[]"
  - history with 10 items → File contains pretty-printed JSON

### Method: delete(self, filename) → bool
- **Location**: Line 6062
- **Signature**: Instance method
- **Input**: filename (string)
- **Logic**:
  1. Constructs path: os.path.join(CHAT_DIR, filename)
  2. Checks if file exists
  3. If exists: Attempts os.remove(path)
    - Returns True if successful
    - Returns False on OSError (logs warning)
  4. If doesn't exist: Returns False
- **Returns**: Boolean (True if deleted successfully)
- **Side Effects**: Removes file from disk
- **Test Cases**:
  - Valid file → True
  - Nonexistent file → False
  - Permission denied → False (logged)

### Helper Methods:
- **append_and_save**(filename, user_msg, model_msg, **extra_fields): Appends both messages to full history
- **append_user_early**(filename, user_msg): Saves user message immediately with placeholder model response
- **update_last_model_response**(filename, model_msg, **extra_fields): Updates the last model entry
- **add_message**(filename, role, content, task="CHAT", model_name="Auto", **extra_fields): Appends single message

