# CONCRETE CODE EXAMPLES & SIGNATURES FROM app.py

## 1. FileOperator - ACTUAL CODE SNIPPETS

### is_file_operation() - Line 2252
\\\python
@classmethod
def is_file_operation(cls, text):
    \"\"\"检测是否是文件操作请求\"\"\"
    text_lower = text.lower()
    return any(kw in text_lower for kw in cls.FILE_KEYWORDS)
\\\

**Test Examples:**
- FileOperator.is_file_operation("读取文件test.txt") → True
- FileOperator.is_file_operation("hello world") → False

---

### _extract_path_from_text() - Line 2268
\\\python
@classmethod
def _extract_path_from_text(cls, user_input: str) -> str:
    \"\"\"Extract a likely filesystem path from user input.\"\"\"
    import re
    
    patterns = [
        r'["\']([^"\']+)["\']',  # Quoted paths
        r'([A-Za-z]:\\\\(?:[^\\\\/:*?"<>|\\r\\n]+\\\\)*[^\\\\/:*?"<>|\\r\\n]*)',  # Windows
        r"(\.?/[\\w\\-./ ]+)",  # Unix
    ]
    for pattern in patterns:
        m = re.search(pattern, user_input)
        if m:
            candidate = m.group(1).strip().strip("，。,.;；")
            if candidate:
                return candidate
    return ""
\\\

**Test Examples:**
- Input: 'Organize "/home/docs"' → Return: "/home/docs"
- Input: 'no path here' → Return: ""

---

### execute() - Line 2286 (MASSIVE METHOD)
\\\python
@classmethod
def execute(cls, user_input):
    \"\"\"执行文件操作\"\"\"
    text_lower = user_input.lower()
    result = {"success": False, "action": "", "message": "", "content": ""}
    
    # Path 1: Folder organize intent
    if cls._is_folder_organize_intent(text_lower):
        folder_path = cls._extract_path_from_text(user_input)
        if not folder_path:
            folder_path = get_default_wechat_files_dir()
        # ... complex folder organization logic ...
        return result
    
    # Path 2: Read file
    if any(kw in text_lower for kw in ["读取", "打开文件", ...]):
        # ... file reading logic, max 10000 chars ...
        return result
    
    # Path 3: List files
    if any(kw in text_lower for kw in ["文件列表", "目录", ...]):
        # ... directory listing logic, max 50 items ...
        return result
    
    # Paths 4-5: Create/write and default
    # ...
    return result
\\\

**Return Dict Keys:**
- success: bool
- action: str ("folder_auto_catalog" | "read_file" | "list_files")
- message: str (status/error message)
- content: str (file contents or directory listing)

---

### get_file_metadata() - Line 2535
\\\python
@classmethod
def get_file_metadata(cls, filepath):
    \"\"\"获取文件元数据\"\"\"
    try:
        if not os.path.exists(filepath):
            return {"success": False, "message": "文件不存在"}
        
        stat = os.stat(filepath)
        from datetime import datetime
        
        return {
            "success": True,
            "filepath": filepath,
            "filename": os.path.basename(filepath),
            "size": f"{stat.st_size / 1024:.2f} KB",
            "created": datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "extension": os.path.splitext(filepath)[1],
            "is_file": os.path.isfile(filepath),
        }
    except Exception as e:
        return {"success": False, "message": f"❌ 无法获取文件信息: {str(e)}"}
\\\

**Test Examples:**
- Valid file → All metadata fields present, size in KB
- Nonexistent file → success=False, message="文件不存在"

---

## 2. WebSearcher - ACTUAL CODE SNIPPETS

### needs_web_search() - Line 2626
\\\python
@classmethod
def needs_web_search(cls, text):
    \"\"\"检测是否需要联网搜索\"\"\"
    text_lower = text.lower()
    
    # 11 regex patterns checked first
    must_search_patterns = [
        r"(能不能|应该不应该|值不值得|是否).*?买",  # Stock advice
        r"(最新|实时|今天|明天|下周).*?(股|行情|数据)",  # Real-time market
        # ... 9 more patterns ...
        r"(几点|什么时候).{0,6}(出发|到|到达|抵达).{0,12}(班|次|票|车|机)",  # Departure time
    ]
    
    import re
    for pattern in must_search_patterns:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return True
    
    # Fallback: keyword check
    if any(kw in text_lower for kw in cls.WEB_KEYWORDS):
        return True
    
    return False
\\\

**Test Examples:**
- "明天从北京到上海的高铁票有吗" → True (travel pattern)
- "你好" → False (no keywords or patterns)

---

### _detect_query_type() - Line 2666
\\\python
@classmethod
def _detect_query_type(cls, query: str) -> str:
    \"\"\"检测搜索查询的意图类型\"\"\"
    q = query.lower()
    
    travel_kw = ["火车票", "高铁票", "动车票", "机票", "余票", ...]
    if any(kw in q for kw in travel_kw):
        return "travel"
    
    weather_kw = ["天气", "气温", "下雨", "下雪", "温度", ...]
    if any(kw in q for kw in weather_kw):
        return "weather"
    
    finance_kw = ["股价", "股票", "汇率", "比特币", "黄金", ...]
    if any(kw in q for kw in finance_kw):
        return "finance"
    
    return "general"
\\\

**Returns:** "travel" | "weather" | "finance" | "general"

---

### _build_search_context() - Line 2721
\\\python
@classmethod
def _build_search_context(cls, query: str, query_type: str) -> tuple:
    \"\"\"根据查询类型返回 (enriched_query, system_instruction)\"\"\"
    if query_type == "travel":
        instruction = (
            "你是 Koto，一个智能出行助手。用户在查询交通出行信息...\\n"
            "请用 Markdown 表格列出主要班次，列标题为：\\n"
            "| 班次 | 出发站 | 到达站 | 出发时间 | 到达时间 | 历时 | 二等座 | 一等座 |\\n"
            "只列出搜索结果中明确出现的班次，不要自行补全或推测。\\n"
        )
        return query, instruction
    
    elif query_type == "weather":
        instruction = (
            "你是 Koto，一个智能助手。请根据搜索结果提供准确的天气信息。\\n"
            "格式要求：\\n1. 当前气温和天气状况\\n2. 今日最高/最低气温\\n..."
        )
        return query, instruction
    
    # ... more cases ...
    return query, instruction
\\\

**Returns:** (str, str) - (query, formatted system instruction)

---

## 3. ContextAnalyzer - ACTUAL CODE SNIPPETS

### extract_entities() - Line 3650
\\\python
@classmethod
def extract_entities(cls, text: str, task_type: str = None) -> list:
    \"\"\"从文本中提取关键实体\"\"\"
    entities = []
    text_lower = text.lower()
    
    # Color extraction
    colors = ["红色", "蓝色", "绿色", "黄色", "白色", "黑色", ...]
    for color in colors:
        if color in text_lower:
            entities.append({"type": "color", "value": color})
    
    # Style extraction
    styles = ["可爱", "帅气", "写实", "卡通", "动漫", ...]
    for style in styles:
        if style in text_lower:
            entities.append({"type": "style", "value": style})
    
    # Subject extraction
    subjects = ["猫", "狗", "人", "风景", "建筑", ...]
    for subject in subjects:
        if subject in text_lower:
            entities.append({"type": "subject", "value": subject})
    
    # Task-specific entities
    if task_type and task_type in cls.TASK_SIGNATURES:
        for entity_keyword in cls.TASK_SIGNATURES[task_type].get("entities", []):
            if entity_keyword in text_lower:
                entities.append({"type": "task_specific", "value": entity_keyword})
    
    return entities
\\\

**Returns:** List[Dict] with keys: type (str), value (str)

---

### analyze_context() - Line 3855 (COMPLEX RAG LOGIC)
\\\python
@classmethod
def analyze_context(cls, user_input: str, history: list) -> dict:
    \"\"\"RAG 风格的上下文分析\"\"\"
    result = {
        "is_continuation": False,
        "related_task": None,
        "continuation_type": None,
        "context_summary": {},
        "enhanced_input": user_input,
        "confidence": 0.0,
    }
    
    if not history or len(history) < 2:
        return result
    
    # 1. Build context summary
    context_summary = cls.build_context_summary(history)
    result["context_summary"] = context_summary
    
    # 2. Detect continuation type with confidence weighting
    detected_type = None
    max_weight = 0.0
    user_lower = user_input.lower()
    input_length = len(user_input)
    
    for pattern_type, pattern_info in cls.CONTINUATION_PATTERNS.items():
        # Check input length limit
        max_len = pattern_info.get("max_input_length")
        if max_len and input_length > max_len:
            continue
        
        # Check for indicator matches
        matches = 0
        for ind in pattern_info["indicators"]:
            if ind in user_lower:
                if pattern_info.get("require_start", False):
                    if user_lower.find(ind) < 10:  # Within first 10 chars
                        matches += 1
                else:
                    matches += 1
        
        if matches > 0:
            adjusted_weight = pattern_info["weight"] * (1 + 0.1 * (matches - 1))
            if adjusted_weight > max_weight:
                max_weight = adjusted_weight
                detected_type = pattern_type
    
    # 3. Check for new topic indicators (reduces weight by 80%)
    new_topic_indicators = ["关于", "一篇", "一份", "一个新的", "帮我写", ...]
    has_new_topic = any(ind in user_lower for ind in new_topic_indicators)
    
    if has_new_topic and input_length > 10:
        max_weight *= 0.2
    
    # 4. Check for task mismatch
    # (logic to clear weight if task type doesn't match previous)
    
    # 5. If confidence > 0.5, mark as continuation
    if detected_type and max_weight > 0.5:
        result["is_continuation"] = True
        result["continuation_type"] = detected_type
        result["confidence"] = min(max_weight, 1.0)
        # Build RAG-enhanced input
        result["enhanced_input"] = cls.build_rag_prompt(
            user_input, context_summary, detected_type
        )
    
    return result
\\\

**Returns:** Dict with keys:
- is_continuation: bool
- related_task: str or None
- continuation_type: str or None ("modify", "reference", "convert", "continue", "detail")
- context_summary: dict
- enhanced_input: str (RAG-formatted)
- confidence: float (0.0-1.0)

---

## 4. Utils - ACTUAL CODE SNIPPETS

### sanitize_string() - Line 5495
\\\python
@staticmethod
def sanitize_string(s):
    if isinstance(s, str):
        return s.encode("utf-8", "ignore").decode("utf-8")
    return s
\\\

**Test:** Utils.sanitize_string("你好") → "你好"

---

### is_failure_output() - Line 5501
\\\python
@staticmethod
def is_failure_output(text: str) -> bool:
    if not text or not str(text).strip():
        return True
    t = str(text).strip().lower()
    if t.startswith("❌") or "失败" in t or "错误" in t:
        return True
    
    _no_internet_phrases = [
        "没有直接联网", "无法直接联网", "无法联网", "没有联网",
        "不能联网", "没有实时", "无法获取实时", "不能获取实时",
        "没有访问互联网", "无法访问互联网",
        "i don't have access to the internet",
        "i cannot access the internet", "i'm unable to access the internet",
        "no internet access", "i don't have real-time",
        "i cannot browse", "i can't browse",
    ]
    return any(phrase in t for phrase in _no_internet_phrases)
\\\

**Tests:**
- "" → True
- "❌ Error" → True
- "i don't have access to the internet" → True
- "Success" → False

---

### detect_required_packages() - Line 5616
\\\python
@staticmethod
def detect_required_packages(text: str) -> list:
    \"\"\"从输出中粗略检测第三方依赖（仅返回白名单内的包）\"\"\"
    if not text:
        return []
    modules = set()
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("import "):
            parts = line.replace("import", "").split(",")
            for p in parts:
                name = p.strip().split(" ")[0]
                if name:
                    modules.add(name)
        elif line.startswith("from "):
            parts = line.split()
            if len(parts) >= 2:
                modules.add(parts[1].strip())
    
    packages = set()
    for mod in modules:
        if mod in Utils._PACKAGE_ALLOWLIST:
            packages.add(Utils._PACKAGE_ALLOWLIST[mod])
    return sorted(packages)
\\\

**Test:**
- Input: "import numpy\\nimport cv2" → ["numpy", "opencv-python"]

---

## 5. SessionManager - ACTUAL CODE SNIPPETS

### list_sessions() - Line 5931
\\\python
def list_sessions(self):
    \"\"\"列出所有会话，按修改时间排序（最新在前）\"\"\"
    files = [f for f in os.listdir(CHAT_DIR) if f.endswith(".json")]
    files_with_time = []
    for f in files:
        path = os.path.join(CHAT_DIR, f)
        mtime = os.path.getmtime(path)
        files_with_time.append((f, mtime))
    files_with_time.sort(key=lambda x: x[1], reverse=True)
    return [f[0] for f in files_with_time]
\\\

**Returns:** List[str] of filenames, newest first

---

### load() - Line 5943
\\\python
def load(self, filename):
    \"\"\"加载会话历史 - 返回用于模型上下文的截断版本\"\"\"
    path = os.path.join(CHAT_DIR, filename)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                full_history = json.load(f)
                # 仅截断用于模型上下文的部分，不影响持久化存储
                return self._trim_history(full_history)
        except (json.JSONDecodeError, OSError) as e:
            _app_logger.warning("Failed to load session %s: %s", filename, e)
            return []
    return []
\\\

**Returns:** List (max 20 turns for model context)

---

### create() - Line 5978
\\\python
def create(self, name):
    safe = "".join([c if c.isalnum() else "_" for c in name])
    filename = f"{safe}.json"
    path = os.path.join(CHAT_DIR, filename)
    
    # 若同名文件已存在，加时间戳后缀避免覆盖
    if os.path.exists(path):
        filename = f"{safe}_{int(time.time())}.json"
        path = os.path.join(CHAT_DIR, filename)
    
    with open(path, "w", encoding="utf-8") as f:
        json.dump([], f)
    return filename
\\\

**Returns:** str (filename created)

---

### save() - Line 5990
\\\python
def save(self, filename, history):
    path = os.path.join(CHAT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
\\\

---

### delete() - Line 6062
\\\python
def delete(self, filename):
    path = os.path.join(CHAT_DIR, filename)
    if os.path.exists(path):
        try:
            os.remove(path)
            return True
        except OSError as e:
            _app_logger.warning("Failed to delete session %s: %s", filename, e)
            return False
    return False
\\\

**Returns:** bool (True if deleted)

