import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 延迟导入 - 这些模块仅在运行时方法调用时加载，避免启动时加载 google.genai (~4.7s) 和 requests (~0.5s)
# from app.core.routing.local_model_router import LocalModelRouter
# from app.core.routing.ai_router import AIRouter
# from app.core.routing.task_decomposer import TaskDecomposer
# from app.core.routing.local_planner import LocalPlanner


def _get_local_model_router():
    from app.core.routing.local_model_router import LocalModelRouter

    return LocalModelRouter


def _get_ai_router():
    from app.core.routing.ai_router import AIRouter

    return AIRouter


def _get_task_decomposer():
    from app.core.routing.task_decomposer import TaskDecomposer

    return TaskDecomposer


def _get_local_planner():
    from app.core.routing.local_planner import LocalPlanner

    return LocalPlanner

def _get_task_classifier():
    from app.core.routing.task_classifier import TaskClassifier
    return TaskClassifier

class SmartDispatcher:
    """
    混合智能路由算法
    1. 首先尝试 AI 路由器（快速、智能）
    2. 如果 AI 超时或失败，回退到本地算法
    """

    # 是否启用 AI 路由
    USE_AI_ROUTER = True

    # 依赖注入容器
    _dependencies = {
        "LocalExecutor": None,
        "ContextAnalyzer": None,
        "WebSearcher": None,
        "MODEL_MAP": {},
        "client": None,
    }

    # LRU result cache: keyed by MD5(user_input), stores full analyze() return tuple.
    # Routing is deterministic for same text, so no TTL needed.
    _route_cache: "OrderedDict" = None
    _route_cache_max = 128
    _route_cache_lock = None

    @classmethod
    def _get_route_cache(cls):
        if cls._route_cache is None:
            import threading as _threading
            from collections import OrderedDict

            cls._route_cache = OrderedDict()
            cls._route_cache_lock = _threading.Lock()
        return cls._route_cache, cls._route_cache_lock

    @classmethod
    def configure(
        cls, local_executor, context_analyzer, web_searcher, model_map, client
    ):
        """配置外部依赖"""
        cls._dependencies["LocalExecutor"] = local_executor
        cls._dependencies["ContextAnalyzer"] = context_analyzer
        cls._dependencies["WebSearcher"] = web_searcher
        cls._dependencies["MODEL_MAP"] = model_map
        cls._dependencies["client"] = client

    # 任务语料库 - 每个任务的锚定表达（精简版，作为余量兜底；主分类由 AI 模型完成）
    TASK_CORPUS = {
        "PAINTER": ["画一张图", "帮我画", "生成图片", "draw me", "generate image"],
        "CODER": [
            "写代码",
            "帮我写个函数",
            "python实现",
            "write code",
            "implement function",
            "帮我作图",
            "作一个折线图",
            "画柱状图",
            "画饼图",
            "生成图表",
            "数据可视化",
            "用matplotlib画",
            "画散点图",
            "plot数据",
            "chart数据",
            "统计图",
        ],
        "FILE_GEN": [
            "生成word文档",
            "做ppt",
            "做一个word",
            "帮我做一份",
            "创建pdf",
            "写一个文档",
            "export excel",
            "生成报告模板",
            "做一个介绍文档",
            "制作幻灯片",
        ],
        "RESEARCH": [
            "深入分析",
            "全面调研",
            "technical principle",
            "in-depth study",
            "对比分析",
        ],
        "WEB_SEARCH": [
            "今天天气",
            "股价多少",
            "最新新闻",
            "current price",
            "比赛结果",
            "目前价格",
            "现在价格",
            "价格多少",
            "原油价格",
            "黄金价格",
            "布伦特原油",
            "WTI原油",
            "白银价格",
            "铜价",
            "期货价格",
            "汇率",
            "今日价",
            "实时价格",
            "加密货币",
            "比特币价格",
            "以太坊价格",
            "黄金行情",
            "原油行情",
            "外汇行情",
            "股市行情",
            "基金净值",
            "债券收益率",
        ],
        "FILE_OP": ["读取文件", "文件列表", "批量重命名", "list files", "整理文件夹"],
        "FILE_EDIT": [
            "修改文件",
            "替换内容",
            "删除第几行",
            "edit file",
            "replace in file",
        ],
        "FILE_SEARCH": ["找文件", "哪个文件", "文件在哪", "find file", "search for"],
        "CHAT": ["你好", "是什么", "介绍一下", "tell me about", "help me understand"],
        "SYSTEM": [
            "打开微信",
            "启动chrome",
            "关闭qq",
            "截图",
            "系统时间",
            "shutdown",
            "关机",
            "打开steam",
            "打开edge",
            "启动vscode",
            "打开计算器",
            "关掉任务管理器",
            "打开加速器",
            "启动游戏",
            "打开软件",
            "运行程序",
        ],
        "AGENT": [
            "发微信",
            "给他发消息",
            "设提醒",
            "设闹钟",
            "帮我买票",
            "订票",
            "提醒我",
            "日历安排",
            "浏览器打开",
            "自动发邮件",
        ],
        "MEETING_EXTRACT": [
            "会议纪要",
            "会议记录",
            "提取会议",
            "整理会议",
            "总结会议",
            "会议要点",
            "提炼会议",
            "会议行动项",
            "会议决策",
            "meeting minutes",
            "extract action items",
        ],
    }

    # 预计算特征 (字符级 n-gram)
    _features = None
    _task_vectors = None

    @classmethod
    def _init_features(cls):
        """初始化特征向量 (懒加载)"""
        if cls._features is not None:
            return

        all_ngrams = set()
        for corpus in cls.TASK_CORPUS.values():
            for text in corpus:
                ngrams = cls._extract_ngrams(text)
                all_ngrams.update(ngrams)

        cls._features = list(all_ngrams)

        cls._task_vectors = {}
        for task, corpus in cls.TASK_CORPUS.items():
            vectors = [cls._text_to_vector(text) for text in corpus]
            avg_vector = [
                sum(v[i] for v in vectors) / len(vectors)
                for i in range(len(cls._features))
            ]
            cls._task_vectors[task] = avg_vector

    @classmethod
    def _compute_similarity_scores(cls, user_input: str) -> dict:
        """计算各任务的相似度分数"""
        if cls._features is None or cls._task_vectors is None:
            cls._init_features()
        user_vector = cls._text_to_vector(user_input)
        return {
            task: cls._cosine_similarity(user_vector, task_vector)
            for task, task_vector in cls._task_vectors.items()
        }

    @classmethod
    def _build_routing_list(
        cls, scores: dict, boosts: dict = None, reasons: dict = None, top_k: int = 6
    ) -> list:
        """构建路由分配列表（用于可视化展示）"""
        boosts = boosts or {}
        reasons = reasons or {}
        routing = []
        for task, score in scores.items():
            final_score = max(score, boosts.get(task, 0))
            reason_list = reasons.get(task, [])
            if not reason_list:
                reason_list = ["similarity"]
            routing.append(
                {
                    "task": task,
                    "score": float(final_score),
                    "reason": " + ".join(reason_list),
                }
            )
        routing.sort(key=lambda x: x["score"], reverse=True)
        return routing[:top_k]

    # ──────────────────────────────────────────────────────────────
    # 极简快速通道：无需任何 AI 分类器即可确认的简单输入
    # ──────────────────────────────────────────────────────────────
    _TRIVIAL_GREETINGS = {
        "你好",
        "你好呀",
        "你好啊",
        "hi",
        "hello",
        "哈喽",
        "嗨",
        "hey",
        "早上好",
        "早安",
        "中午好",
        "下午好",
        "晚上好",
        "晚安",
        "谢谢",
        "谢谢你",
        "谢了",
        "感谢",
        "多谢",
        "thanks",
        "thank you",
        "再见",
        "拜拜",
        "bye",
        "goodbye",
        "下次见",
        "好的",
        "好",
        "嗯",
        "嗯嗯",
        "明白了",
        "知道了",
        "收到",
        "ok",
        "okay",
    }
    _TRIVIAL_IDENTITY = [
        "你是谁", "你叫什么", "你叫啥", "你是什么", "介绍一下你自己", "你是koto", "koto是什么",
    ]
    # 若存在这些词，再短也不能走极简通道
    _TRIVIAL_EXCLUDE = [
        "画", "图片", "照片", "图", "代码", "程序", "脚本", "文件", "文档", "报告",
        "pdf", "word", "excel", "ppt", "天气", "股价", "新闻", "汇率",
        "打开", "关闭", "截图", "启动", "运行", "搜索",
        "微信", "发送", "发消息", "发邮件", "购票",
        "研究", "分析", "深入", "全面",
        # 图表/数据可视化 — 防止「帮我作图」被误判为极简 CHAT
        "作图",
        "图表",
        "折线图",
        "柱状图",
        "饼图",
        "散点图",
        "直方图",
        "可视化",
        "统计图",
        "数据图",
        "chart",
        "plot",
        "matplotlib",
        "seaborn",
        "plotly",
        # 金融/商品资产词 — 防止「布伦特原油价格」被短句极简通道误判为 CHAT
        "原油",
        "布伦特",
        "黄金",
        "白银",
        "铜价",
        "期货",
        "汇率",
        "比特币",
        "以太坊",
        "价格",
        "行情",
        "走势",
        "现价",
        "涨跌",
        # 金价/油价等简写形式
        "金价",
        "油价",
        "银价",
        "气价",
        # 天气相关变体
        "下雨",
        "下雪",
        "气温",
        "天气",
        # 编程/代码关键词 — 防止「帮我写个Python排序函数」被极简通道误判为 CHAT
        "python",
        "javascript",
        "java",
        "golang",
        "rust",
        "c++",
        "sql",
        "函数",
        "算法",
        "脚本",
        "接口",
        "api",
        # 时效性信号词 — 防止「目前金价」「近期AI动态」被极简通道漏判
        "目前", "近期", "局势", "战况", "动态", "进展", "现状", "近况",
    ]

    @classmethod
    def _is_trivial_input(cls, user_input: str) -> bool:
        """
        判断是否为极简输入，可不经任何 AI 分类器、直接路由到 CHAT + 本地模型。
        条件：
          1. 是已知问候/致谢/确认词，或
          2. 是简短身份询问（≤20字），或
          3. 长度 ≤15 字且不含复杂任务关键词
        """
        text = user_input.strip()
        tl = text.lower()

        if tl in cls._TRIVIAL_GREETINGS:
            return True

        if len(text) <= 20 and any(kw in tl for kw in cls._TRIVIAL_IDENTITY):
            return True

        if len(text) <= 15 and not any(k in tl for k in cls._TRIVIAL_EXCLUDE):
            return True

        return False

    @classmethod
    def get_trivial_reply(cls, user_input: str) -> str:
        """
        为极简输入返回内置快速响应（本地模型不可用时使用，避免调用云端）。
        匹配顺序：精确问候词 > 感谢 > 告别 > 确认 > 通用兜底。
        """
        tl = user_input.strip().lower()
        if tl in {"你好", "你好呀", "你好啊", "hi", "hello", "哈喽", "嗨", "hey"}:
            return "你好！😊 有什么我可以帮您？"
        if tl in {"早上好", "早安"}:
            return "早上好！☀️ 今天有什么需要帮忙？"
        if tl in {"中午好"}:
            return "中午好！🌤️ 需要帮忙吗？"
        if tl in {"下午好"}:
            return "下午好！有什么我可以帮您的？"
        if tl in {"晚上好"}:
            return "晚上好！🌙 今晚有什么需要帮忙？"
        if tl in {"晚安"}:
            return "晚安！🌙"
        if tl in {"谢谢", "谢谢你", "谢了", "感谢", "多谢", "thanks", "thank you"}:
            return "不客气！😊 有需要随时叫我。"
        if tl in {"再见", "拜拜", "bye", "goodbye", "下次见"}:
            return "再见！👋 有需要随时回来找我。"
        if tl in {"好的", "好", "明白了", "知道了", "收到", "ok", "okay"}:
            return "好的，有需要随时说。"
        if tl in {"嗯", "嗯嗯"}:
            return "嗯，有什么我可以帮到您？"
        return "有什么需要帮忙的？😊"

    @staticmethod
    def _extract_ngrams(text, n=2):
        """提取字符级 n-gram"""
        text = text.lower().strip()
        ngrams = set()
        for char in text:
            if char.strip():
                ngrams.add(char)
        for i in range(len(text) - 1):
            if text[i : i + 2].strip():
                ngrams.add(text[i : i + 2])
        return ngrams

    @classmethod
    def _quick_task_hint(cls, user_input: str) -> str:
        text_lower = user_input.lower()
        # 数据图表/可视化 — 必须在通配"图"之前检查，否则折线图/柱状图/作图会被误送 PAINTER
        if any(
            k in text_lower
            for k in [
                "图表",
                "折线图",
                "柱状图",
                "饼图",
                "散点图",
                "直方图",
                "作图",
                "可视化",
                "统计图",
                "数据图",
                "chart",
                "plot",
                "matplotlib",
                "seaborn",
                "plotly",
                "echarts",
            ]
        ):
            return "CODER"
        # AI 绘画/图片生成（通配"图"放在图表检查之后）
        if any(
            k in text_lower
            for k in ["画", "图片", "照片", "生成图", "绘制", "绘图", "ai画", "图"]
        ):
            return "PAINTER"
        if any(
            k in text_lower for k in ["代码", "编程", "python", "javascript", "函数"]
        ):
            return "CODER"
        if any(k in text_lower for k in ["查", "搜索", "价格", "天气", "新闻"]):
            return "WEB_SEARCH"
        # 系统操作：命令动词开头 + 短输入
        _sys_starters = ("打开", "启动", "运行", "开启", "关闭", "退出", "关掉", "杀掉")
        _sys_exclude = ("怎么", "如何", "什么", "文件", "网页", "网站", "思路", "方法")
        stripped = user_input.strip()
        if (
            len(stripped) <= 18
            and any(stripped.startswith(s) for s in _sys_starters)
            and not any(k in text_lower for k in _sys_exclude)
        ):
            return "SYSTEM"
        # 提醒/消息 → AGENT
        if any(
            k in text_lower
            for k in ["提醒我", "提醒一下", "设闹钟", "设提醒", "发微信"]
        ):
            return "AGENT"
        # 当输入附带文件前缀 [FILE_ATTACHED:ext] 时，优先判断是编辑已有文件还是生成新文件
        # 避免 "[FILE_ATTACHED:.docx]" 中的 "docx" 直接触发 FILE_GEN 误路由
        if "[file_attached:" in text_lower:
            _file_edit_hints = [
                "修改",
                "更改",
                "标注",
                "批注",
                "润色",
                "改写",
                "校对",
                "审校",
                "修订",
                "纠错",
                "改善",
                "优化",
                "调整",
                "精炼",
                "通畅",
                "整体修改",
                "通顺",
                "流畅",
                "精简",
                "凝练",
                "简洁",
                "整理",
                "梳理",
                "提炼",
                "修一下",
                "帮我改",
                "改一改",
                "改得",
                "写得",
                "改写",
                "polish",
                "refine",
                "revise",
            ]
            if any(k in text_lower for k in _file_edit_hints):
                return "DOC_ANNOTATE"
        if any(
            k in text_lower
            for k in [
                "word",
                "pdf",
                "docx",
                "表格",
                "文档",
                "报告",
                "生成",
                "做成",
                "标注",
                "批注",
                "润色",
                "改写",
                "校对",
                "审校",
                "修订",
                "纠错",
            ]
        ):
            return "FILE_GEN"
        if any(k in text_lower for k in ["研究", "分析", "深入", "介绍"]):
            return "RESEARCH"
        return "CHAT"

    @classmethod
    def _text_to_vector(cls, text):
        if cls._features is None:
            cls._init_features()
        ngrams = cls._extract_ngrams(text)
        vector = [1 if f in ngrams else 0 for f in cls._features]
        return vector

    @staticmethod
    def _cosine_similarity(v1, v2):
        dot_product = sum(a * b for a, b in zip(v1, v2))
        norm1 = sum(a * a for a in v1) ** 0.5
        norm2 = sum(b * b for b in v2) ** 0.5
        if norm1 == 0 or norm2 == 0:
            return 0
        return dot_product / (norm1 * norm2)

    @classmethod
    def _get_dep(cls, name):
        """Helper to get dependency safely"""
        return cls._dependencies.get(name)

    @staticmethod
    def _should_use_annotation_system(user_input, has_file=False):
        """Simplistic check if annotation system should be used"""
        # This logic was previously inline or imported, implementing basic check here
        keywords = [
            "标注",
            "批注",
            "润色",
            "改写",
            "校对",
            "审校",
            "修订",
            "纠错",
            "改善",
            "优化",
            "修改",
        ]
        quality_words = ["不合适", "生硬", "翻译腔", "语序", "用词", "逻辑", "问题"]
        target_words = ["翻译", "文章", "文档", "内容", "文本", "段落", "句子", "字词"]

        if not has_file:
            return False

        has_kw = any(k in user_input for k in keywords)
        has_qw = any(q in user_input for q in quality_words)
        has_target = any(t in user_input for t in target_words)

        return has_kw or (has_qw and has_target)

    @classmethod
    def _apply_routing_safety(
        cls,
        task_type: str,
        user_input: str,
        user_lower: str,
        file_context,
        LocalExecutor,
        WebSearcher,
    ) -> str:
        """对模型输出应用强规则安全覆写，避免模型分类器误判边界情况。"""
        if task_type == "CHAT" and WebSearcher and WebSearcher.needs_web_search(user_input):
            return "WEB_SEARCH"
        if (
            task_type not in ("SYSTEM", "AGENT")
            and LocalExecutor
            and LocalExecutor.is_system_command(user_input)
        ):
            return "SYSTEM"
        _agent_pat = [
            r"发微信", r"回微信", r"微信发", r"微信回",
            r"给.{1,6}发消息", r"给.{1,6}发微信",
            r"浏览器打开", r"点击.{1,6}按键",
        ]
        if any(re.search(p, user_input) for p in _agent_pat):
            return "AGENT"
        if task_type == "DOC_ANNOTATE" and not (
            file_context and file_context.get("has_file")
        ):
            return "CHAT"
        return task_type

    @classmethod
    def analyze(cls, user_input: str, history=None, file_context=None):
        """
        智能分析用户输入，返回最匹配的任务类型
        优先级：规则检测 > 本地快速模型 > RAG > 远程AI > 本地语料

        返回: (task_type, confidence_info, context_info)
        """
        import hashlib as _hashlib

        start_time = time.time()

        # Cache lookup — skip for requests with file_context (state may differ)
        if not file_context:
            cache_key = _hashlib.md5(user_input.encode()).hexdigest()[:16]
            cache, lock = cls._get_route_cache()
            with lock:
                if cache_key in cache:
                    cache.move_to_end(cache_key)
                    return cache[cache_key]
        else:
            cache_key = None
            cache = None
            lock = None

        # Get dependencies
        LocalExecutor = cls._get_dep("LocalExecutor")
        ContextAnalyzer = cls._get_dep("ContextAnalyzer")
        WebSearcher = cls._get_dep("WebSearcher")
        client = cls._get_dep("client")

        # 初始化特征 (首次调用)
        cls._init_features()

        user_lower = user_input.lower().strip()
        context_info = None
        similarity_scores = cls._compute_similarity_scores(user_input)
        base_routing_list = cls._build_routing_list(similarity_scores)

        # 剥离 [FILE_ATTACHED:ext] 前缀用于长度判断和极简通道检测
        # （该前缀由 app.py 注入以辅助本地模型，但不应影响 trivial/short 判断）
        _input_for_trivial = re.sub(
            r"^\[FILE_ATTACHED:[^\]]+\]\s*", "", user_input
        ).strip()

        # === 0. Force Plan Mode (New Feature) ===
        _FORCE_PLAN_TRIGGERS = [
            "请制定计划", "拆解任务", "帮我计划", "分步骤", "一步步",
            "分步完成", "制定方案", "拆分任务", "步骤规划",
            "step by step", "step-by-step", "plan and execute",
        ]
        if user_input.strip().startswith("/plan ") or any(t in user_input for t in _FORCE_PLAN_TRIGGERS):
            context_info = {"complexity": "complex", "is_multi_step_task": True}
            context_info["multi_step_info"] = {
                "pattern": "forced_plan",
                "description": "User forced planning mode",
            }
            context_info["routing_list"] = cls._build_routing_list(
                similarity_scores,
                boosts={"MULTI_STEP": 1.0},
                reasons={"MULTI_STEP": ["user_forced"]},
            )
            return "MULTI_STEP", "🛠️ Forced-Plan", context_info

        # === 优先：文件附件处理 logic ===
        if file_context and file_context.get("has_file"):
            file_ext = file_context.get("file_type", "")
            edit_keywords = [
                "修改", "更改", "标注", "批注", "润色", "改写", "校对", "审校", "修订",
                "纠错", "改善", "优化", "调整", "精炼", "通畅", "通顺", "流畅", "精简",
                "凝练", "简洁", "整理", "梳理", "提炼", "整体修改", "修一下", "帮我改",
                "改一改", "改得", "写得", "polish", "refine", "revise", "edit", "improve",
            ]
            has_edit_intent = any(kw in user_lower for kw in edit_keywords)
            
            if has_edit_intent and file_ext in [".docx", ".doc"]:
                context_info = {"complexity": "complex"}
                context_info["routing_list"] = cls._build_routing_list(
                    similarity_scores,
                    boosts={"DOC_ANNOTATE": 1.0},
                    reasons={"DOC_ANNOTATE": ["rule:doc_annotate"]},
                )
                logger.info(
                    f"[SmartDispatcher] 📄 检测到 Word 文档标注请求: {file_ext}"
                )
                return "DOC_ANNOTATE", "📄 Doc-Annotate", context_info
            elif has_edit_intent and file_ext in [".md", ".txt"]:
                context_info = {"complexity": "complex", "is_multi_step_task": True}
                context_info["multi_step_info"] = {
                    "pattern": "document_workflow",
                    "description": "文档智能编辑工作流",
                }
                context_info["routing_list"] = cls._build_routing_list(
                    similarity_scores,
                    boosts={"MULTI_STEP": 1.0},
                    reasons={"MULTI_STEP": ["rule:doc_workflow"]},
                )
                logger.info(f"[SmartDispatcher] 📄 检测到文件编辑请求: {file_ext}")
                return "MULTI_STEP", "📄 Doc-Workflow", context_info

        # === 快速通道: 超短输入（用去前缀的原始文本判断）===
        if len(_input_for_trivial) <= 3:
            if LocalExecutor and LocalExecutor.is_system_command(_input_for_trivial):
                context_info = context_info or {}
                context_info["routing_list"] = cls._build_routing_list(
                    similarity_scores,
                    boosts={"SYSTEM": 1.0},
                    reasons={"SYSTEM": ["rule:standalone_command"]},
                )
                return "SYSTEM", "🖥️ Rule-Detected", context_info
            return "CHAT", "⚡ Quick", None

        # === 指定路径文件列举快速通道（最高优先级，防止被误路由到 FILE_GEN/CHAT）===
        # 匹配：输入含 Windows 路径（如 C:\xxx）且含列举/归纳/查找意图关键词
        if re.search(r'[A-Za-z]:[\\]', user_input):
            _path_list_kws = [
                "归纳", "列出", "列举", "有哪些", "所有", "全部",
                "找", "查", "看看", "显示", "汇总", "整理",
                # Watch Mode / 字段提取 / 问答
                "监控", "监视", "停止监控", "自动归类",
                "提取", "关键信息", "合同信息", "解读", "分析",
                "哪个", "哪些", "里面", "这几份", "对比",
                # 内容过滤搜索（如"哪几个是报告/合同/简历/访谈"）
                "哪几", "几个", "几份", "路径下", "下有", "下面有",
                "属于", "什么文件", "文件类型", "下的文件",
            ]
            if any(k in user_input for k in _path_list_kws):
                context_info = context_info or {}
                context_info["routing_list"] = cls._build_routing_list(
                    similarity_scores,
                    boosts={"FILE_SEARCH": 1.0},
                    reasons={"FILE_SEARCH": ["rule:path_listing"]},
                )
                logger.info(
                    f"[SmartDispatcher] 📁 指定路径列举快速通道: '{user_input[:40]}' → FILE_SEARCH"
                )
                return "FILE_SEARCH", "📁 Path-Listing", context_info

        # === 系统操作快速通道（打开/启动/关闭 + 应用名，不依赖 APP_ALIASES）===
        # 命令语气、短输入、不含问句/文件/网页关键词
        _sys_action_starters = ("打开", "启动", "运行", "开启", "关闭", "退出", "关掉", "杀掉")
        _sys_exclude_kws = (
            "怎么", "如何", "什么", "为什么", "能不能", "可以吗", "怎样", "咋",
            "文件", "网页", "网址", "url", "网站", "链接", "附件",
            "思路", "方式", "方法", "问题", "功能",
        )
        _stripped = user_input.strip()
        if (
            len(_stripped) <= 18
            and any(_stripped.startswith(s) for s in _sys_action_starters)
            and not any(k in user_lower for k in _sys_exclude_kws)
        ):
            context_info = context_info or {}
            context_info["routing_list"] = cls._build_routing_list(
                similarity_scores,
                boosts={"SYSTEM": 1.0},
                reasons={"SYSTEM": ["rule:action_verb_direct"]},
            )
            logger.info(
                f"[SmartDispatcher] 🖥️ 系统操作快速通道: '{_stripped}' → SYSTEM"
            )
            return "SYSTEM", "🖥️ Action-Direct", context_info

        # === 能力询问 / 方法咨询 → CHAT (在所有动作路由之前) ===
        # 识别非执行型查询：用户在问 Koto「能不能做X」或「怎么做X」，不应触发动作路由
        # 典型误触发：「你会做ppt么」「如何制作Word」「怎么生成图表」「你能画图吗」
        _CAPABILITY_PREFIXES = [
            "你会", "你能", "能不能", "你可以", "能否", "可以吗", "你支持", "支持吗",
        ]
        _HOWTO_PREFIXES = ["怎么", "如何", "怎样", "怎么样", "什么是", "怎么用"]
        _QUESTION_ENDINGS = ["吗", "么", "?", "？", "嘛", "不"]
        _ACTION_TOOL_KWS = [
            "ppt", "幻灯片", "演示文稿", "word", "docx", "pdf", "excel", "文档",
            "图片", "图表", "折线图", "柱状图", "画图", "绘图", "代码", "程序", "音频",
        ]
        _u_stripped_lower = user_lower.rstrip()
        # 1) 能力询问：以「你会/你能/能不能…」开头 + 以「吗/么」结尾
        if (
            any(_u_stripped_lower.startswith(p) for p in _CAPABILITY_PREFIXES)
            and any(_u_stripped_lower.endswith(s) for s in _QUESTION_ENDINGS)
        ):
            context_info = context_info or {}
            context_info["routing_list"] = cls._build_routing_list(
                similarity_scores,
                boosts={"CHAT": 1.0},
                reasons={"CHAT": ["rule:capability_query"]},
            )
            logger.info(
                f"[SmartDispatcher] 💬 能力询问快速通道: '{user_input[:30]}' → CHAT"
            )
            return "CHAT", "💬 Capability-Query", context_info
        # 2) 方法询问：「怎么做X / 如何制作X」— 开头为 how-to prefix + 含功能关键词
        if (
            any(_u_stripped_lower.startswith(p) for p in _HOWTO_PREFIXES)
            and any(k in user_lower for k in _ACTION_TOOL_KWS)
        ):
            context_info = context_info or {}
            context_info["routing_list"] = cls._build_routing_list(
                similarity_scores,
                boosts={"CHAT": 1.0},
                reasons={"CHAT": ["rule:howto_query"]},
            )
            logger.info(
                f"[SmartDispatcher] 💬 方法询问快速通道: '{user_input[:30]}' → CHAT"
            )
            return "CHAT", "💬 HowTo-Query", context_info

        # === 提醒/日程/消息发送快速通道 → AGENT ===
        _AGENT_NOTIFY_PATTERNS = [
            r'(设置?|帮我设?)(提醒|闹钟|定时).{0,20}',
            r'提醒我.{0,25}(点|时|分|号|日)',
            r'(给|向).{1,8}(发|回)(微信|消息|邮件)',
            r'(发|回)(微信|消息).{0,15}给.{1,8}',
        ]
        if any(re.search(p, user_input) for p in _AGENT_NOTIFY_PATTERNS):
            context_info = context_info or {}
            context_info["routing_list"] = cls._build_routing_list(
                similarity_scores,
                boosts={"AGENT": 1.0},
                reasons={"AGENT": ["rule:agent_notify_direct"]},
            )
            logger.info(
                f"[SmartDispatcher] 🤖 提醒/消息快速通道: '{user_input[:30]}' → AGENT"
            )
            return "AGENT", "🤖 Notify-Direct", context_info

        # === AI绘画/图片生成快速通道（在极简通道之前，防止短句被误分到 CHAT）===
        # 匹配：画/做/生成 + 一张/个/幅 + 任意内容 + 图/图片/照片；或含明确图片生成词
        _PAINTER_PATTERNS = [
            r'(画|做|生成|创作|绘制|帮我画|帮我做|帮我生成).{0,20}(图片|照片|壁纸|头像|封面)',
            r'(画|做|生成|创作|绘制|帮我画|帮我做|帮我生成).{0,3}(一张|一幅|一个|张|幅).{0,30}图',
            r'(一张|一幅).{1,20}(图|图片|照片)',
            r'(ai|AI).{0,5}(画|绘|生成|创作)',
        ]
        import re as _re_painter
        if any(_re_painter.search(p, user_input) for p in _PAINTER_PATTERNS):
            # 排除图表/可视化词（那些走 CODER）
            _not_chart = not any(k in user_lower for k in [
                "图表", "折线图", "柱状图", "饼图", "散点图", "直方图", "条形图",
                "可视化", "统计图", "数据图", "chart", "plot", "matplotlib",
            ])
            if _not_chart:
                context_info = context_info or {}
                context_info["routing_list"] = cls._build_routing_list(
                    similarity_scores,
                    boosts={"PAINTER": 1.0},
                    reasons={"PAINTER": ["rule:image_gen"]},
                )
                logger.info(
                    f"[SmartDispatcher] 🎨 图片生成快速通道: '{user_input[:30]}' → PAINTER"
                )
                return "PAINTER", "🎨 Image-Direct", context_info

        # === 极简通道: 明显的闲聊/问候/简短问答，跳过所有分类器 ===
        # 使用去掉 [FILE_ATTACHED:ext] 前缀的原始文本，避免前缀膨胀导致误分类
        if cls._is_trivial_input(_input_for_trivial):
            context_info = context_info or {}
            context_info["routing_list"] = cls._build_routing_list(
                similarity_scores,
                boosts={"CHAT": 1.0},
                reasons={"CHAT": ["rule:trivial"]},
            )
            logger.info(
                f"[SmartDispatcher] ⚡ 极简通道: '{_input_for_trivial[:20]}' → CHAT (跳过分类器)"
            )
            return "CHAT", "⚡ Trivial", context_info

        # === 早期主分类器（TaskClassifier + 本地 Ollama）===
        # 在所有领域关键词规则之前运行，让模型首先有机会理解意图。
        # 置信度≥ 0.72 就立即返回；低于阈値时将结果缓存到 _early_model_result，
        # 关键词规则后面会再以 0.62 作为二次安全网。
        _early_model_result = None  # (task, conf_float, conf_str, hint, complexity)
        try:
            _TC = _get_task_classifier()
            if _TC.is_available():
                _tc_task, _tc_conf = _TC.classify(user_input)
                if _tc_conf >= 0.72:
                    _tc_task = cls._apply_routing_safety(
                        _tc_task, user_input, user_lower,
                        file_context, LocalExecutor, WebSearcher,
                    )
                    context_info = context_info or {}
                    context_info["routing_list"] = cls._build_routing_list(
                        similarity_scores,
                        boosts={_tc_task: _tc_conf},
                        reasons={_tc_task: ["early:task_classifier"]},
                    )
                    logger.info(
                        f"[SmartDispatcher] 🚀 早期TaskClassifier: '{user_input[:30]}' → {_tc_task} ({_tc_conf:.2f})"
                    )
                    return _tc_task, f"🚀 TaskClassifier {_tc_conf:.2f}", context_info
        except Exception as _tce:
            logger.warning(f"[SmartDispatcher] ⚠️ 早期TaskClassifier异常（跳过）: {_tce}")
        try:
            _lmr = _get_local_model_router()
            if _lmr.is_ollama_available():
                _lm_task, _lm_cs, _lm_src, _lm_hint, _lm_cplx = \
                    _lmr.classify_with_hint(user_input, timeout=3.5)
                _lm_conf = 0.0
                if isinstance(_lm_cs, str):
                    _mm = re.search(r"(\d+\.\d+)", _lm_cs)
                    if _mm:
                        _lm_conf = float(_mm.group(1))
                # 缓存结果供后面关键词规则抚质时复用（避免二次调用 Ollama）
                _early_model_result = (_lm_task, _lm_conf, _lm_cs, _lm_hint, _lm_cplx)
                if _lm_task and _lm_conf >= 0.72:
                    _lm_task = cls._apply_routing_safety(
                        _lm_task, user_input, user_lower,
                        file_context, LocalExecutor, WebSearcher,
                    )
                    context_info = context_info or {}
                    context_info["routing_list"] = cls._build_routing_list(
                        similarity_scores,
                        boosts={_lm_task: _lm_conf},
                        reasons={_lm_task: ["early:local_model"]},
                    )
                    if _lm_hint:
                        context_info["skill_prompt"] = _lm_hint
                    if _lm_cplx == "complex" and _lm_task != "CHAT":
                        context_info["complexity"] = "complex"
                    logger.info(
                        f"[SmartDispatcher] 🤖 早期本地模型: '{user_input[:30]}' → {_lm_task} ({_lm_conf:.2f})"
                    )
                    return _lm_task, f"🤖 EarlyLocal {_lm_conf:.2f}", context_info
        except Exception as _lme:
            logger.warning(f"[SmartDispatcher] ⚠️ 早期本地模型异常（跳过）: {_lme}")

        # 模型不可用或置信度不足 0.72 → 继续领域关键词规则（将作为安全底层兆底）

        # === 天气 / 实时信息快速通道（在 Trivial 之后、模型不足时兆底）===
        _WEATHER_KWS = [
            "天气", "气温", "下雨吗", "下雨", "下雪吗", "下雪", "天气怎么样", "天气怎样",
            "天气预报", "weather", "温度多少", "穿什么衣服",
        ]
        if any(k in user_lower for k in _WEATHER_KWS):
            context_info = context_info or {}
            context_info["routing_list"] = cls._build_routing_list(
                similarity_scores,
                boosts={"WEB_SEARCH": 1.0},
                reasons={"WEB_SEARCH": ["rule:weather_direct"]},
            )
            logger.info(
                f"[SmartDispatcher] 🌤️ 天气实时快速通道: '{user_input[:30]}' → WEB_SEARCH"
            )
            return "WEB_SEARCH", "🌤️ Weather-Direct", context_info

        # === 会议提炼快速通道 ===
        _MEETING_VERBS = ["提炼", "提取", "整理", "总结", "分析", "归纳"]
        _MEETING_NOUNS = ["会议", "纪要", "会议记录", "会议内容", "转录", "会议文字"]
        # 排除知识性问句（「会议纪要怎么写」/ 「什么是会议纪要」不应触发提炼任务）
        _MEETING_QUESTION_GUARDS = [
            "什么是", "是什么", "怎么写", "如何写", "怎么做", "如何做", "怎么用", "有什么区别",
        ]
        if (
            any(v in user_lower for v in _MEETING_VERBS)
            and any(n in user_lower for n in _MEETING_NOUNS)
            and not any(g in user_lower for g in _MEETING_QUESTION_GUARDS)
        ):
            context_info = context_info or {}
            context_info["routing_list"] = cls._build_routing_list(
                similarity_scores,
                boosts={"MEETING_EXTRACT": 1.0},
                reasons={"MEETING_EXTRACT": ["rule:meeting_extract_direct"]},
            )
            logger.info(
                f"[SmartDispatcher] 📝 会议提炼快速通道: '{user_input[:30]}' → MEETING_EXTRACT"
            )
            return "MEETING_EXTRACT", "📝 Meeting-Extract-Direct", context_info

        # === 代码编写快速通道（在本地模型之前，避免 koto-router 误判明确写代码请求）===
        # 条件：含写作动词 + 编程语言/代码概念，但不是"帮我写一段自我介绍"这类纯文本
        _CODE_WRITE_VERBS = ["帮我写", "给我写", "写一个", "写个", "实现", "编写", "开发", "编程"]
        _CODE_CONCEPTS = [
            "函数", "算法", "类", "接口", "脚本", "程序", "代码",
            "排序", "查找", "递归", "遍历", "爬虫", "api", "模块",
        ]
        _CODE_LANGS = [
            "python", "javascript", "java", "c++", "golang", "rust",
            "typescript", "kotlin", "swift", "php", "ruby", "sql",
        ]
        _has_code_verb = any(v in user_lower for v in _CODE_WRITE_VERBS)
        _has_code_concept = any(c in user_lower for c in _CODE_CONCEPTS)
        _has_code_lang = any(l in user_lower for l in _CODE_LANGS)
        if _has_code_verb and (_has_code_concept or _has_code_lang):
            context_info = context_info or {}
            context_info["routing_list"] = cls._build_routing_list(
                similarity_scores,
                boosts={"CODER": 1.0},
                reasons={"CODER": ["rule:code_write_direct"]},
            )
            logger.info(
                f"[SmartDispatcher] 💻 代码编写快速通道: '{user_input[:30]}' → CODER"
            )
            return "CODER", "💻 Code-Write-Direct", context_info

        # === 时效性关键词快速通道（目前/近期/最新 + 时事主题）===
        _REALTIME_SIGNALS = ["目前", "现在", "当前", "最新", "近期", "今日", "近况"]
        _REALTIME_TOPIC_KWS = [
            "新闻", "消息", "进展", "动态", "局势", "战况", "现状", "情况",
            "比分", "结果", "成绩", "排名", "股价", "金价", "油价",
        ]
        _REALTIME_EXCLUDE_KWS = ["历史", "是什么", "什么是", "定义", "原理", "原因", "介绍", "解释"]
        if (
            any(s in user_lower for s in _REALTIME_SIGNALS)
            and any(t in user_lower for t in _REALTIME_TOPIC_KWS)
            and not any(e in user_lower for e in _REALTIME_EXCLUDE_KWS)
        ):
            context_info = context_info or {}
            context_info["routing_list"] = cls._build_routing_list(
                similarity_scores,
                boosts={"WEB_SEARCH": 1.0},
                reasons={"WEB_SEARCH": ["rule:realtime_signal"]},
            )
            logger.info(
                f"[SmartDispatcher] ⏰ 时效信息快速通道: '{user_input[:30]}' → WEB_SEARCH"
            )
            return "WEB_SEARCH", "⏰ Realtime-Direct", context_info

        # === 数据图表/可视化快速通道（在所有模型之前，防止被误路由到 PAINTER/CHAT）===
        _CHART_KWS = [
            "图表", "折线图", "柱状图", "饼图", "散点图", "直方图", "条形图", "热力图",
            "作图", "可视化", "统计图", "数据图", "chart", "plot", "graph",
            "matplotlib", "seaborn", "plotly", "echarts",
        ]
        _CHART_ACTION_KWS = [
            "画", "作", "生成", "做", "绘制", "创建", "画出", "plot", "draw", "show", "显示",
        ]
        # 排除知识性问句（「什么是折线图」/ 「折线图是什么」→ CHAT 知识回答）
        _CHART_KNOWLEDGE_GUARDS = [
            "什么是", "是什么", "怎么", "如何", "定义", "原理", "介绍", "解释",
        ]
        if any(k in user_lower for k in _CHART_KWS) and not any(
            g in user_lower for g in _CHART_KNOWLEDGE_GUARDS
        ):
            # 包含图表类型词就直接走 CODER（数据可视化），不必配合动作词
            context_info = context_info or {}
            context_info["routing_list"] = cls._build_routing_list(
                similarity_scores,
                boosts={"CODER": 1.0},
                reasons={"CODER": ["rule:chart_viz"]},
            )
            logger.info(
                f"[SmartDispatcher] 📊 图表可视化快速通道: '{user_input[:30]}' → CODER"
            )
            return "CODER", "📊 Chart-Direct", context_info

        # === 实时出行查询快速通道（在所有模型之前，确保不被误判为CHAT/AGENT）===
        _travel_search_patterns = [
            r'(查|查询|查一下|看|有没有|有无|还有).{0,8}(火车票|高铁票|动车票|机票|余票|班次)',
            r'(下周|明天|后天|今天|大后天|[0-9]+[号日]).{0,14}(去|到|从).{0,14}(高铁|动车|火车|航班|机票)',
            r'(去|从).{1,14}(去|到).{1,20}(火车|高铁|动车|机)',
            r'(几点|什么时候).{0,8}(从|到|出发|到达).{0,12}(车|班|次|机)',
            r'(余票|时刻表|列车时刻|航班动态|航班查询)',
        ]
        import re as _re_travel
        if any(_re_travel.search(p, user_input) for p in _travel_search_patterns):
            _buy_kw_early = ["订票", "买票", "购票", "帮我买", "帮我订", "12306"]
            if any(k in user_lower for k in _buy_kw_early):
                context_info = context_info or {}
                context_info["routing_list"] = cls._build_routing_list(
                    similarity_scores,
                    boosts={"AGENT": 1.0},
                    reasons={"AGENT": ["rule:ticket_buy"]},
                )
                return "AGENT", "🤖 Ticket-Buy", context_info
            context_info = context_info or {}
            context_info["routing_list"] = cls._build_routing_list(
                similarity_scores,
                boosts={"WEB_SEARCH": 1.0},
                reasons={"WEB_SEARCH": ["rule:travel_query"]},
            )
            logger.info(
                f"[SmartDispatcher] 🌐 出行查询快速通道: '{user_input[:30]}' → WEB_SEARCH"
            )
            return "WEB_SEARCH", "🌐 Travel-Query", context_info

        # === 金融/商品价格快速通道（价格 = 实时数据，强制 WEB_SEARCH）===
        _PRICE_ASSETS = [
            "原油", "布伦特", "wti", "天然气", "黄金", "白银", "铜", "铁矿石",
            "大豆", "小麦", "棉花", "黄铜", "铝", "锌", "铅", "镍",
            "比特币", "以太坊", "btc", "eth", "加密货币", "数字货币",
            "美元", "欧元", "日元", "英镑", "港币", "外汇", "汇率",
            "a股", "港股", "道琼斯", "纳斯达克", "标普", "上证", "深证",
            "期货", "基金", "债券", "股票",
            # 简写形式（如「目前金价」「油价多少」）
            "金价", "油价", "银价", "铜价",
        ]
        _PRICE_SIGNALS = [
            "价格", "现价", "报价", "行情", "走势", "涨跌", "多少钱",
            "今日价", "实时", "最新价", "开盘", "收盘", "涨了", "跌了",
        ]
        _has_asset = any(k in user_lower for k in _PRICE_ASSETS)
        _has_price_signal = any(k in user_lower for k in _PRICE_SIGNALS)
        # 资产名称 + 价格信号词 → 强制 WEB_SEARCH（无需时效词）
        # 纯资产名称（无价格词）也路由 WEB_SEARCH，因询问资产名称本身通常是为了了解价格
        if _has_asset and (_has_price_signal or len(user_input.strip()) <= 12):
            context_info = context_info or {}
            context_info["routing_list"] = cls._build_routing_list(
                similarity_scores,
                boosts={"WEB_SEARCH": 1.0},
                reasons={"WEB_SEARCH": ["rule:financial_price"]},
            )
            logger.info(
                f"[SmartDispatcher] 💹 金融价格快速通道: '{user_input[:30]}' → WEB_SEARCH"
            )
            return "WEB_SEARCH", "💹 Price-Direct", context_info

        # === 多步任务抢先规划（Pre-empt）===
        # 对于强信号多步输入（如"查询X然后生成Y"），在模型分类前直接触发 LocalPlanner
        # 这样可避免单任务路由器把复合任务误拆为单步
        try:
            _LocalPlannerCls = _get_local_planner()
            if _LocalPlannerCls.should_preempt(user_input):
                _early_plan = _LocalPlannerCls.plan(user_input, timeout=5.0)
                if (
                    _early_plan
                    and _early_plan.get("use_planner")
                    and len(_early_plan.get("steps", [])) >= 2
                ):
                    context_info = context_info or {}
                    context_info["is_multi_step_task"] = True
                    context_info["multi_step_info"] = {
                        "pattern": "local_plan",
                        "subtasks": _early_plan["steps"],
                    }
                    context_info["routing_list"] = cls._build_routing_list(
                        similarity_scores,
                        boosts={"MULTI_STEP": 1.0},
                        reasons={"MULTI_STEP": ["preempt:local_planner"]},
                    )
                    logger.info(
                        f"[SmartDispatcher] 🧭 多步抢先规划成功: {len(_early_plan['steps'])} 步 → MULTI_STEP"
                    )
                    return "MULTI_STEP", "🧭 Preempt-Plan", context_info
        except Exception as _pe:
            logger.info(f"[SmartDispatcher] ⚠️ 多步抢先规划异常（跳过）: {_pe}")

        # === 分类器二次兜底（关键词规则均未命中 / 模型早期置信度在 0.62-0.71）===
        # 优先复用早期调用的缓存结果（避免二次调用 Ollama），阈值降为 0.62 作为安全网。
        # 同时修复原有 bug：在线模式下模型结果也正常返回（原来仅 if not client 才 return）。
        _SEC_THRESH = 0.62
        # 先尝试 TaskClassifier 二次找回（早期未命中时可能模型刚完成加载）
        try:
            _TC2 = _get_task_classifier()
            if _TC2.is_available():
                _tc2_task, _tc2_conf = _TC2.classify(user_input)
                if _tc2_conf >= _SEC_THRESH:
                    _tc2_task = cls._apply_routing_safety(
                        _tc2_task, user_input, user_lower,
                        file_context, LocalExecutor, WebSearcher,
                    )
                    context_info = context_info or {}
                    context_info["routing_list"] = cls._build_routing_list(
                        similarity_scores,
                        boosts={_tc2_task: _tc2_conf},
                        reasons={_tc2_task: ["tc_2nd_chance"]},
                    )
                    logger.info(
                        f"[SmartDispatcher] 🚀 TC二次兜底: '{user_input[:30]}' → {_tc2_task} ({_tc2_conf:.2f})"
                    )
                    return _tc2_task, f"🚀 TaskClassifier(2) {_tc2_conf:.2f}", context_info
        except Exception:
            pass
        # 复用早期缓存的 Ollama 结果（减少重复请求）
        if _early_model_result is not None:
            _em_task, _em_conf, _em_cs, _em_hint, _em_cplx = _early_model_result
            if _em_task and _em_conf >= _SEC_THRESH:
                _em_task = cls._apply_routing_safety(
                    _em_task, user_input, user_lower,
                    file_context, LocalExecutor, WebSearcher,
                )
                context_info = context_info or {}
                context_info["routing_list"] = cls._build_routing_list(
                    similarity_scores,
                    boosts={_em_task: _em_conf},
                    reasons={_em_task: ["local_model_2nd_chance"]},
                )
                if _em_hint:
                    context_info["skill_prompt"] = _em_hint
                if _em_cplx == "complex" and _em_task != "CHAT":
                    context_info["complexity"] = "complex"
                logger.info(
                    f"[SmartDispatcher] 🤖 Ollama二次兜底: '{user_input[:30]}' → {_em_task} ({_em_conf:.2f})"
                )
                return _em_task, f"🤖 LocalModel(2) {_em_conf:.2f}", context_info
        else:
            # 早期未能调用 Ollama（当时不可用），现在再试一次（含离线模式）
            try:
                _lmr2 = _get_local_model_router()
                if _lmr2.is_ollama_available():
                    _r2_task, _r2_cs, _, _r2_hint, _r2_cplx = \
                        _lmr2.classify_with_hint(user_input, timeout=4.5)
                    _r2_conf = 0.0
                    if isinstance(_r2_cs, str):
                        _mm2 = re.search(r"(\d+\.\d+)", _r2_cs)
                        if _mm2:
                            _r2_conf = float(_mm2.group(1))
                    if _r2_task and _r2_conf >= _SEC_THRESH:
                        _r2_task = cls._apply_routing_safety(
                            _r2_task, user_input, user_lower,
                            file_context, LocalExecutor, WebSearcher,
                        )
                        context_info = context_info or {}
                        context_info["routing_list"] = cls._build_routing_list(
                            similarity_scores,
                            boosts={_r2_task: _r2_conf},
                            reasons={_r2_task: ["local_model_late"]},
                        )
                        if _r2_hint:
                            context_info["skill_prompt"] = _r2_hint
                        if _r2_cplx == "complex" and _r2_task != "CHAT":
                            context_info["complexity"] = "complex"
                        logger.info(
                            f"[SmartDispatcher] 🤖 Ollama延迟起动: '{user_input[:30]}' → {_r2_task} ({_r2_conf:.2f})"
                        )
                        return _r2_task, f"🤖 LocalModel(late) {_r2_conf:.2f}", context_info
            except Exception:
                pass

        # === 关键词兜底规则（所有模型均失败时最后路障）===
        logger.debug(f"[SmartDispatcher] ⚠️ 模型均未达阈值，回退关键词兜底规则: '{user_input[:30]}'")

        # -- 附件文档标注 (需要 file_context 支撑，不纯靠关键词) --
        if file_context and file_context.get("has_file"):
            _fc_ext = file_context.get("file_type", "")
            if _fc_ext in [".doc", ".docx"]:
                try:
                    if cls._should_use_annotation_system(user_input, has_file=True):
                        context_info = {"complexity": "complex"}
                        context_info["routing_list"] = cls._build_routing_list(
                            similarity_scores,
                            boosts={"DOC_ANNOTATE": 1.0},
                            reasons={"DOC_ANNOTATE": ["fallback:annotation_with_file"]},
                        )
                        return "DOC_ANNOTATE", "📄 Fallback-Annotation", context_info
                except Exception:
                    pass

        # -- PPT 直通 (需要同时有 PPT 关键词 + 动作词，且不是能力询问/方法问句) --
        _ppt_direct_keywords = ["ppt", "幻灯片", "演示文稿", "presentation", "slide", "slides", ".pptx"]
        _ppt_action_words = ["做", "生成", "创建", "制作", "做一个", "做个", "帮我做", "帮我生成"]
        _ppt_question_guards = [
            "怎么", "如何", "什么", "你会", "你能", "能不能", "可以吗", "能否", "支持",
        ]
        if (
            any(k in user_lower for k in _ppt_direct_keywords)
            and any(a in user_lower for a in _ppt_action_words)
            and not any(q in user_lower for q in _ppt_question_guards)
        ):
            context_info = {"complexity": "complex"}
            context_info["routing_list"] = cls._build_routing_list(
                similarity_scores,
                boosts={"FILE_GEN": 1.0},
                reasons={"FILE_GEN": ["fallback:ppt_direct"]},
            )
            logger.info(f"[SmartDispatcher] 🎯 PPT 请求直通 FILE_GEN")
            return "FILE_GEN", "📄 PPT-Direct", context_info

        # -- 文档/报告生成直通 (Word/PDF/Excel 等明确输出格式 + 动作意图，不含PPT已有规则) --
        _doc_gen_output_kws = ["word", "docx", ".doc", "pdf", "excel", ".xlsx", "报告", "文档", "介绍文档", "word版"]
        _doc_gen_action_kws = ["做一个", "做一份", "做个", "写一份", "写一个", "帮我做", "帮我写",
                               "生成一个", "生成一份", "生成", "创建一个", "创建一份", "制作"]
        _doc_question_guards = [
            "怎么", "如何", "什么", "你会", "你能", "能不能", "可以吗", "能否", "支持", "功能",
        ]
        if (
            any(k in user_lower for k in _doc_gen_output_kws)
            and any(a in user_lower for a in _doc_gen_action_kws)
            and not any(q in user_lower for q in _doc_question_guards)
        ):
            context_info = context_info or {"complexity": "complex"}
            context_info["complexity"] = "complex"
            context_info["routing_list"] = cls._build_routing_list(
                similarity_scores,
                boosts={"FILE_GEN": 1.0},
                reasons={"FILE_GEN": ["fallback:doc_gen_direct"]},
            )
            logger.info(
                f"[SmartDispatcher] 📄 文档生成请求直通 FILE_GEN: '{user_input[:30]}'"
            )
            return "FILE_GEN", "📄 DocGen-Direct", context_info

        # -- 全盘文件搜索/打开（优先于系统命令，避免"打开xxx文件"被误判为SYSTEM）--
        _file_search_patterns = [
            r"帮我找.{0,20}文件", r"找一下.{1,30}", r"找找.{1,30}",
            r"找到.{1,20}文件", r"定位.{1,20}文件", r"搜索文件",
            r"在哪(里|儿|个目录)", r"哪个文件.{0,10}",
            r"扫描(我的)?(电脑|磁盘|硬盘|文件)", r"全盘扫描",
            r"帮我打开.{1,30}(文件|\.)",
        ]
        import re as _re
        if any(_re.search(p, user_input) for p in _file_search_patterns):
            context_info = context_info or {}
            context_info["routing_list"] = cls._build_routing_list(
                similarity_scores,
                boosts={"FILE_SEARCH": 1.0},
                reasons={"FILE_SEARCH": ["rule:disk_file_search"]},
            )
            logger.info(f"[SmartDispatcher] 🔍 文件搜索/全盘扫描直通 FILE_SEARCH")
            return "FILE_SEARCH", "🔍 FileSearch-Direct", context_info

        # -- 系统命令 --
        if LocalExecutor and LocalExecutor.is_system_command(user_input):
            context_info = context_info or {}
            context_info["routing_list"] = cls._build_routing_list(
                similarity_scores,
                boosts={"SYSTEM": 0.9},
                reasons={"SYSTEM": ["fallback:system"]},
            )
            return "SYSTEM", "🖥️ Fallback-System", context_info

        # -- 系统命令兜底：命令动词 + 短输入（不依赖 APP_ALIASES）--
        _fb_sys_starters = ("打开", "启动", "运行", "开启", "关闭", "退出", "关掉", "杀掉")
        _fb_sys_exclude = ("怎么", "如何", "什么", "文件", "网页", "网站", "思路", "方法", "功能")
        _stripped_fb = user_input.strip()
        if (
            len(_stripped_fb) <= 18
            and any(_stripped_fb.startswith(s) for s in _fb_sys_starters)
            and not any(k in user_lower for k in _fb_sys_exclude)
        ):
            context_info = context_info or {}
            context_info["routing_list"] = cls._build_routing_list(
                similarity_scores,
                boosts={"SYSTEM": 0.9},
                reasons={"SYSTEM": ["fallback:action_verb"]},
            )
            logger.info(f"[SmartDispatcher] 🖥️ 系统命令兜底: '{_stripped_fb}' → SYSTEM")
            return "SYSTEM", "🖥️ Fallback-ActionVerb", context_info

        # -- 多步任务规划 --
        _LocalPlanner = _get_local_planner()
        if _LocalPlanner.can_plan(user_input):
            plan = _LocalPlanner.plan(user_input)
            if plan and plan.get("use_planner") and plan.get("steps"):
                context_info = context_info or {}
                context_info["is_multi_step_task"] = True
                context_info["multi_step_info"] = {
                    "pattern": "local_plan",
                    "subtasks": plan.get("steps", []),
                }
                context_info["routing_list"] = cls._build_routing_list(
                    similarity_scores,
                    boosts={"MULTI_STEP": 0.95},
                    reasons={"MULTI_STEP": ["fallback:local_planner"]},
                )
                return "MULTI_STEP", "🧭 Fallback-Plan", context_info

        initial_task_hint = cls._quick_task_hint(user_input)
        compound_info = _get_task_decomposer().detect_compound_task(
            user_input, initial_task_hint
        )

        if compound_info["is_compound"]:
            context_info = {
                "is_multi_step_task": True,
                "multi_step_info": compound_info,
            }
            context_info["routing_list"] = base_routing_list
            try:
                _ma_preset = _get_task_decomposer().suggest_multiagent_preset(compound_info)
                context_info["multiagent_preset"] = _ma_preset
            except Exception:
                pass
            return "MULTI_STEP", "🔄 Fallback-MultiStep", context_info

        # -- RAG 上下文延续 --
        if history and len(history) >= 2 and ContextAnalyzer:
            context_info = ContextAnalyzer.analyze_context(user_input, history)
            if context_info.get("is_continuation") and context_info.get("related_task") == "WEB_SEARCH":
                search_verbs = ["查", "搜", "搜索", "查询", "找", "再找", "再查", "再搜", "再看看"]
                if any(v in user_lower for v in search_verbs):
                    context_info["routing_list"] = cls._build_routing_list(
                        similarity_scores,
                        boosts={"WEB_SEARCH": 0.9},
                        reasons={"WEB_SEARCH": ["fallback:search_followup"]},
                    )
                    return "WEB_SEARCH", "🌐 Fallback-SearchFollowup", context_info
        
        # -- 网页搜索检测 --
        if WebSearcher and WebSearcher.needs_web_search(user_input):
            context_info = context_info or {}
            context_info["routing_list"] = cls._build_routing_list(
                similarity_scores,
                boosts={"WEB_SEARCH": 0.9},
                reasons={"WEB_SEARCH": ["fallback:web_search"]},
            )
            return "WEB_SEARCH", "🌐 Fallback-WebSearch", context_info
        
        # -- RAG 历史延续 --
        if history and len(history) >= 2 and ContextAnalyzer:
            context_info = ContextAnalyzer.analyze_context(user_input, history)
            
            if context_info.get("is_continuation") and context_info.get("confidence", 0) > 0.7:
                related_task = context_info.get("related_task")
                continuation_type = context_info.get("continuation_type", "unknown")
                
                if related_task:
                    context_info["routing_list"] = cls._build_routing_list(
                        similarity_scores,
                        boosts={related_task: 0.88},
                        reasons={related_task: [f"fallback:rag_{continuation_type}"]}
                    )
                    return related_task, f"🔗 Fallback-RAG-{continuation_type}", context_info
        
        # === 最终兜底：ML 相似度 → 默认 CHAT ===
        scores = similarity_scores
        best_task = max(scores, key=scores.get)
        best_score = scores[best_task]
        latency = (time.time() - start_time) * 1000

        if best_score > 0.45:
            _q_words = ["怎么", "如何", "什么", "为什么", "能不能", "可以吗",
                        "怎样", "咋", "啥", "how", "what", "why", "which"]
            is_q = any(qw in user_lower for qw in _q_words)
            if is_q and best_score < 0.6 and best_task != "CHAT":
                pass
            else:
                confidence = f"🧠 ML ({best_score:.0%}, {latency:.1f}ms)"
                context_info = context_info or {}
                context_info["routing_list"] = cls._build_routing_list(
                    similarity_scores,
                    boosts={best_task: best_score},
                    reasons={best_task: ["similarity_best"]},
                )
                return best_task, confidence, context_info

        context_info = context_info or {}
        context_info["routing_list"] = base_routing_list
        result = ("CHAT", f"💬 Default ({latency:.1f}ms)", context_info)
        if cache_key and cache is not None and lock is not None:
            with lock:
                cache[cache_key] = result
                cache.move_to_end(cache_key)
                if len(cache) > cls._route_cache_max:
                    cache.popitem(last=False)
        return result

    @classmethod
    def get_model_for_task(cls, task_type, has_image=False, complexity="normal"):
        """根据任务类型获取最优模型（自动跳过当前不可用的模型）"""
        MODEL_MAP = cls._get_dep("MODEL_MAP")
        if not MODEL_MAP:
            MODEL_MAP = {"CHAT": "gemini-2.5-flash"}

        # ── 咨询 ModelFallbackExecutor：若首选模型当前不可用，直接返回备选 ──
        try:
            from app.core.llm.model_fallback import get_fallback_executor
            _fbe = get_fallback_executor()
        except Exception:
            _fbe = None

        def _avail(preferred: str, fb_task: str = task_type) -> str:
            """若 preferred 当前可用则直接返回；否则从降级链取第一个可用模型。"""
            if _fbe and not _fbe.is_available(preferred):
                alt = _fbe.get_best_available(task_type=fb_task, preferred=preferred)
                if alt and alt != preferred:
                    import logging as _log
                    _log.getLogger(__name__).warning(
                        "[Dispatcher] 模型 %s 当前不可用，改用 %s (task=%s)",
                        preferred, alt, task_type,
                    )
                    return alt
            return preferred

        if task_type == "FILE_GEN":
            if complexity == "complex":
                return MODEL_MAP.get("COMPLEX", MODEL_MAP.get("CODER", "gemini-3.1-pro-preview"))
            return MODEL_MAP.get("FILE_GEN", "gemini-3-flash-preview")
        
        if task_type == "DOC_ANNOTATE":
            if complexity == "complex":
                return MODEL_MAP.get("COMPLEX", MODEL_MAP.get("CODER", "gemini-3.1-pro-preview"))
            return MODEL_MAP.get("DOC_ANNOTATE", "gemini-3-flash-preview")
            
        if task_type == "RESEARCH":
            return MODEL_MAP.get("RESEARCH", "gemini-3.1-pro-preview")
        
        if task_type == "CODER":
            return MODEL_MAP.get("CODER", "gemini-3.1-pro-preview")

        # 多步复杂任务 → Pro 模型确保执行质量
        if task_type == "MULTI_STEP":
            return MODEL_MAP.get("MULTI_STEP", MODEL_MAP.get("CODER", "gemini-3.1-pro-preview"))

        # CHAT 任务始终使用 Flash，不因复杂度升级到 Pro
        if task_type == "CHAT":
            _chat_candidate = MODEL_MAP.get("CHAT", "gemini-3-flash-preview")
            # 安全网：如果 ModelManager 将 CHAT 路由到 Pro 模型（tier>7），强制回退到 Flash
            _FLASH_FALLBACK = "gemini-3-flash-preview"
            try:
                from web.model_manager import KNOWN_MODEL_REGISTRY
                _candidate_tier = KNOWN_MODEL_REGISTRY.get(_chat_candidate, {}).get("tier", 5)
                if _candidate_tier > 7:
                    import logging as _lg
                    _lg.getLogger(__name__).warning(
                        "[Dispatcher] CHAT MODEL_MAP 指向 tier-%d 模型 %s，强制回退到 %s",
                        _candidate_tier, _chat_candidate, _FLASH_FALLBACK,
                    )
                    _chat_candidate = _FLASH_FALLBACK
            except Exception:
                pass
            return _avail(_chat_candidate)

        # 通用复杂度升级：非 CHAT 任务标记为 complex 时使用较强模型
        if complexity == "complex":
            return MODEL_MAP.get("COMPLEX", "gemini-3.1-pro-preview")

        if has_image and task_type != "PAINTER":
            return _avail(MODEL_MAP.get("VISION", MODEL_MAP.get("CHAT", "gemini-2.5-flash")), "VISION")

        return _avail(MODEL_MAP.get(task_type, MODEL_MAP.get("CHAT", "gemini-2.5-flash")))

    # ── LangGraph 工作流集成 ────────────────────────────────────────────────
    @classmethod
    def resolve_workflow(cls, task_type: str, user_input: str, has_file: bool = False) -> str:
        """
        根据 dispatch() 返回的 task_type 决定是否使用 LangGraph 多步工作流。

        Args:
            has_file: 请求是否附带已上传文件。为 True 时跳过 LangGraph 工作流，
                      因为工作流没有文件字节上下文，强制使用文件分析流（legacy）。

        返回值:
            "langgraph_react"          → 使用 LangGraphAgent（单 Agent ReAct）
            "langgraph_research_doc"   → 使用 WorkflowEngine: research_and_document
            "langgraph_multi_agent_ppt"→ 使用 WorkflowEngine: multi_agent_ppt
            "legacy"                   → 保持原有 UnifiedAgent 处理路径

        集成方式（在 web/app.py 或对应处理函数中）:
            task_type, conf, ctx = SmartDispatcher.dispatch(user_input, ...)
            wf = SmartDispatcher.resolve_workflow(task_type, user_input, has_file=has_file)
            if wf.startswith("langgraph_"):
                # 使用 LangGraph 路径
                ...
        """
        try:
            from app.core.workflow.langgraph_workflow import WorkflowEngine
            detected = WorkflowEngine.detect_workflow(task_type, user_input, has_file=has_file)
            if detected == "multi_agent_ppt":
                return "langgraph_multi_agent_ppt"
            elif detected == "research_and_document":
                return "langgraph_research_doc"
            elif task_type == "MULTI_STEP" and not has_file:
                # 通用多步任务 → LangGraphAgent ReAct（有文件时不走 LangGraph）
                return "langgraph_react"
            else:
                return "legacy"
        except ImportError:
            # langgraph 未安装 → 回退到原有路径
            return "legacy"
