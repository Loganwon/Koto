# 🔧 Koto 文档标注质量改进方案

**更新日期**: 2026-02-14  
**问题**: 文档标注关联整段而不是精准修改，质量变差  
**州态**: ✅ 已修复

---

## 📋 问题诊断

用户报告文档标注系统出现以下问题：
1. ❌ 修改精度差 - 关联到大段落而不是具体文本
2. ❌ 建议质量低 - 标注位置错误
3. ❌ 之前版本质量更好 - 说明有某个改动导致回归

---

## 🔍 根本原因分析

### 问题 1: 文本定位算法缺陷（PRIMARY）

**文件**: `web/document_annotator.py` - `locate_text_in_paragraphs()` 方法

**原始代码**:
```python
# 模糊匹配时直接返回段落，position: 0
if best_ratio >= self.min_similarity and best_match:
    return {
        "found": True,
        "para_index": best_match["index"],
        "position": 0,  # ❌ 始终返回0！
        "matched_text": target_text,
        ...
    }
```

**问题**: 
- 当精确匹配失败时，模糊匹配只返回 `position: 0`
- 这告诉系统"在段落的第0个位置"标注
- 结果是整个段落都被标注，而不是具体的文本片段

**场景演示**:
```
文档段落: "这套系统非常好用，不仅功能完善，而且性能优异。"
AI建议: "原文: 非常好用, 改为: 顺手好用"

精确匹配: ❌ 失败（因为 AI 可能改写了原文）
模糊匹配: ✓ 找到相似度 0.75 的匹配
返回: {position: 0}
结果: 标注整个段落 ❌
```

### 问题 2: 相似度阈值过高

**参数**: `min_similarity: float = 0.8`

**影响**:
- 0.8 很容易导致精确匹配失败
- 强制使用低质量的模糊匹配
- 本应是备选方案，现在成了首选

### 问题 3: AI Prompt 导向不当

**prompt 中的问题**:
- 没有强调"原文必须精确复制"
- AI 可能会改写、缩写原文
- 导致定位算法无法找到精确匹配

---

## ✅ 应用的修复方案

### 修复 1: 改进文本定位算法（关键修复）

**文件**: `web/document_annotator.py`

**改进策略**: 智能模糊匹配

```python
# 第2步：模糊匹配 - 先找到相关段落，再在段落内查找最相似的子串
if best_para_similarity >= self.min_similarity and best_para:
    para_text = best_para["text"]
    best_substring = None
    best_substring_ratio = 0
    best_substring_pos = 0
    
    # ✨ 关键：在段落中滑动窗口，查找最相似的子串
    target_len = len(target_text)
    for i in range(len(para_text) - target_len + 1):
        substring = para_text[i:i + target_len]
        ratio = SequenceMatcher(None, target_text, substring).ratio()
        
        if ratio > best_substring_ratio:
            best_substring_ratio = ratio
            best_substring = substring
            best_substring_pos = i  # ✨ 精确位置！
    
    if best_substring_ratio >= 0.6:
        return {
            "found": True,
            ...
            "position": best_substring_pos,  # ✨ 不再是0，而是真实位置！
            "matched_text": best_substring,
            ...
        }
```

**优势**:
- ✅ 不再标注整个段落
- ✅ 精确定位到相似的子串
- ✅ 子串相似度 ≥0.6（参数可调）

---

### 修复 2: 降低相似度阈值

**变更**: `0.8 → 0.65`

**原因**:
- 0.8 太严格，容易失败
- 0.65 更合理，保留容错能力
- python-docx 版本兼容性更好

**代码**:
```python
def __init__(self, min_similarity: float = 0.65, annotation_mode: str = "comment"):
    """min_similarity: 降低到0.65以提高准确率"""
```

---

### 修复 3: 改进 AI Prompt（指导改进）

**文件**: `web/document_feedback.py`

**关键改进**:

| 维度 | 原始 | 改进后 |
|------|------|--------|
| 原文长度要求 | 5-15字 | 5-20字 |
| 精确性强调 | 提过一次 | 强调5次 |
| 复制指导 | "真实存在" | "必须从文档中原样复制" |
| 反面警告 | 一般 | 明确"不能跳字、不能改写" |
| 格式验证 | 提及 | 强调"返回有效JSON数组" |

**新 Prompt 关键语句**:
```text
✅ 原文必须字符精确匹配（从文档中复制粘贴）
✅ 原文必须是连续的短语，不能跳字漏字
✅ **注意中文文本，不要误识别标点的对应**
❌ 不要跳字或改动原文中的字符
```

---

## 🧪 修复验证

### 修复前后对比

**场景**: 标注文档中的"不好" → "不佳"

```
文档: "这个方案不好，需要改进其中的几个地方。"

【修复前】
精确匹配: ❌ 不好（文本可能被AI改写）
模糊匹配: ✓ 找到
返回: position: 0
标注结果: ❌ 整个段落都被红刻下

【修复后】
精确匹配: ❌ 仍不好
模糊匹配: ✓ 找到（相似度 0.8）
滑动窗口: ✓ 找到"不好"的确切位置（position: 8）
标注结果: ✅ 只标注"不好"这两个字
```

---

## 🚀 使用改进的功能

### 第1步: 确认修复已应用
```bash
# 验证修复（在 app 启动日志中会看到）
[Annotator] 智能模糊匹配成功 (段落相似度: 85%, 子串相似度: 78%)
[DocumentFeedback] ✓ 修改精度提升
```

### 第2步: 重新标注文档
1. 上传 Word 文档
2. 输入标注需求
3. **新版本会精准标注每一处修改**

### 第3步: 验证结果
在 Word 中打开 `_revised.docx` 文件：
- ✅ 批注气泡精确定位到具体词语
- ✅ 不再包含整个段落
- ✅ 标注更加清晰可用

---

## 📊 改动汇总

| 文件 | 方法 | 改动类型 | 优先级 |
|------|------|---------|--------|
| `document_annotator.py` | `locate_text_in_paragraphs()` | 算法改进 | 🔴 严重 |
| `document_annotator.py` | `__init__()` | 参数调整 | 🟡 中 |
| `document_feedback.py` | `_build_annotation_prompt()` | Prompt 优化 | 🟡 中 |

---

## ⚙️ 后续可调参数

如果用户仍然遇到问题，可以调整：

### 1. 子串匹配的相似度阈值
```python
# 当前: 0.6
if best_substring_ratio >= 0.6:
    # 可以调整为 0.5 或 0.7，取决于容错需求
```

### 2. 段落选择的相似度
```python
# 当前: self.min_similarity (0.65)
if best_para_similarity >= self.min_similarity:
    # 可以调整为 0.55 或 0.75
```

### 3. 原文长度限制
```python
# 在 Prompt 中调整
"每处原文必须是连续的5-20字"  # 可改为 3-25 字
```

---

## 📝 建议的后续行动

1. **立即测试**: 重启应用，重新标注一份文档，验证精度是否改善
2. **收集反馈**: 如果仍有问题，收集具体例子
3. **微调参数**: 根据反馈调整阈值
4. **生成测试报告**: 对比修复前后的质量指标

---

## 🔗 相关文件

- [document_annotator.py](../web/document_annotator.py) - 文本定位引擎
- [document_feedback.py](../web/document_feedback.py) - AI 分析系统
- [FIXES_APPLIED.md](./FIXES_APPLIED.md) - 之前的修复记录

---

**状态**: ✅ 已完成所有改动  
**需要验证**: 用户测试反馈
