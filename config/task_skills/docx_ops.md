# 文档, word, docx, 合同, 报告, 修改, 编辑
# Skill: Word 文档操作

## 常见任务模式

### 文档分析
1. 用 `read_docx_content` 获取结构化段落
2. 用 `llm_extract` 或 `llm_transform` 处理内容
3. 返回分析结果

### 内容修改
1. `read_docx_content` 读取当前内容
2. `llm_transform` 按要求修改文本
3. 通过 `editor_live_update` 推送修改到前端

### 跨文件内容搬运
1. 用 `parse_file_to_text` 读取源文件
2. 用 `llm_extract` 提取目标内容
3. 用 `llm_transform` 按目标格式重组
4. 写入目标位置

## 注意事项
- `read_docx_content` 返回段落级别的结构化数据（text + style）
- `parse_file_to_text` 返回纯文本，适合快速概览
- 复杂格式操作优先使用 `run_python_code` + python-docx
