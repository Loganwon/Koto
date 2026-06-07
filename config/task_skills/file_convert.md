# 转换, 格式, pdf, pptx, csv, 导出, 批量
# Skill: 文件转换与批量处理

## 常见任务模式

### 格式转换
1. 用 `parse_file_to_text` 读取源文件
2. 用 `run_python_code` 执行格式转换
3. 用 `create_file` 保存输出

### 批量文件处理
1. 用 `list_workspace_files` 列出目标文件
2. 循环处理每个文件（read → process → write）
3. 汇报处理结果

### 数据合并
1. 读取多个源文件
2. 用 `run_python_code` 合并数据
3. 写入目标文件

## 注意事项
- 转换前先确认源文件格式和内容
- 批量操作每步都报告进度
- 大文件分批处理避免超时
