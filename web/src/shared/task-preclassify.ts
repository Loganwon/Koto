/**
 * Client-side task pre-classification to reduce /api/analyze latency.
 *
 * Heuristics that can skip the server round-trip for obvious cases.
 * Falls back to /api/analyze when uncertain.
 */

export interface PreClassification {
  task: string;
  confidence: "high" | "low";
}

const FILE_ACTIONS = /(?:修改|编辑|翻译|总结|分析|优化|检查|审核|批改|生成|创建|制作|导出|转换|对比|比较|合并|拆分|提取|整理|格式化|压缩|修复|处理|撰写|编写|润色|改写|改进|完善|审阅|批注|查看|阅读)/;

const FILE_TARGETS = /(?:文档|文件|表格|PPT|PDF|图片|报告|合同|简历|论文|文章|代码|数据|图表|幻灯片|演示文稿|工作簿|电子表格)/;

const CHAT_PATTERNS = /^(?:你好|hi|hello|hey|请问|什么是|怎么|如何|为什么|能不能|可以|帮我|介绍一下|解释|说明|告诉我|教我|推荐|建议|你觉得|有哪些|怎么样|是谁|在哪里|什么时候)/;

/** Fast client-side heuristic -- skip /api/analyze for high-confidence matches. */
export function preClassifyTask(message: string, hasFile: boolean, _fileType?: string): PreClassification | null {
  const text = (message || "").trim();

  // Empty or file-only but no message: defer to server
  if (!text && hasFile) return null;

  // File attachment + explicit task-like language -> FILE task
  if (hasFile) {
    if (FILE_ACTIONS.test(text) && FILE_TARGETS.test(text)) {
      return { task: "FILE", confidence: "high" };
    }
    if (FILE_ACTIONS.test(text)) {
      return { task: "FILE", confidence: "high" };
    }
  }

  // Short conversational messages -> CHAT
  if (!hasFile && text.length < 50 && !text.includes("\n")) {
    if (CHAT_PATTERNS.test(text)) {
      return { task: "CHAT", confidence: "high" };
    }
  }

  // Uncertain -- fall back to server
  return null;
}
