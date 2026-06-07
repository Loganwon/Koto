# 表格, excel, 填写, 数据, 单元格, sheet
# Skill: Excel 表格数据操作

## 常见任务模式

### 数据填充（表格A → 表格B）
1. 先用 `read_sheet_data` 读取源表格和目标表格
2. 分析两个表格的列结构，找到匹配的字段
3. 用 `run_python_code` 编写数据匹配和映射逻辑
4. 用 `write_sheet_data` 将结果写入目标表格

### 数据提取
1. 用 `read_sheet_data` 读取表格
2. 用 `llm_extract` 或 `run_python_code` 提取所需信息
3. 以 JSON 或文本形式返回结果

### 数据汇总
1. 读取所有相关表格
2. 用 `run_python_code` (pandas) 做聚合计算
3. 将结果写入新表格或返回文本

## 注意事项
- `write_sheet_data` 的 updates 参数必须是 JSON 字符串
- row/col 从 1 开始计数
- 写入前会自动创建 .bak 备份
- 大量数据处理优先使用 `run_python_code` + openpyxl/pandas
