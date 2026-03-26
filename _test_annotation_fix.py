"""Quick validation test for annotation fixes."""
import sys, json
sys.path.insert(0, '.')
from web.document_feedback import DocumentFeedbackSystem

# Test _strip_markdown_for_annotation
test_md = (
    "# 文档分析\n\n"
    "**文件名**: test.docx\n"
    "**文件类型**: WORD\n\n"
    "## 文档内容\n\n"
    "### 第三章 研究方法\n\n"
    "- 研究采用了定性分析的方法\n\n"
    "**重要结论**：这一方法在提升效率方面  ← [此段落有格式变化]\n\n"
    "本研究[核心](颜色:FF0000)发现如下"
)

result = DocumentFeedbackSystem._strip_markdown_for_annotation(test_md)
print("=== Strip Test ===")
print(result)
print()

# Test _parse_annotation_response with long original and markdown in 原文
dfs = DocumentFeedbackSystem(gemini_client=None)
long_orig_json = json.dumps([
    {
        "原文": "在当前数字艺术发展的主流实践中，研究者们主要聚焦于三个核心方向：技术驱动的创新探索、社会文化的批判性介入以及跨学科的融合实践。这种多元化的研究态势。",
        "改为": "当前数字艺术研究主要集中在三个方向。",
        "原因": "去冗余"
    },
    {
        "原文": "### 第三章结论",
        "改为": "优化了结论",
        "原因": "标题去markdown"
    },
    {
        "原文": "进行分析",
        "改为": "分析",
        "原因": "去冗余"
    },
    {
        "原文": "**研究方法**采用了定性和定量相结合",
        "改为": "研究方法采用了定性和定量相结合",
        "原因": "去markdown"
    },
])
parsed = dfs._parse_annotation_response(long_orig_json)
print("=== Parse Test ===")
for item in parsed:
    orig = item["原文片段"]
    print(f"  原文({len(orig)}字): {orig!r}")

print("\n=== Test PASSED ===" if len(parsed) >= 2 else "\n=== ISSUE: fewer items than expected ===")
