# Excel 数据分析功能

Koto 现已支持强大的 Excel 数据分析能力！

## 功能特性

### 1. 智能数据识别
- 自动识别客户名称、金额、数量、单价等列
- 如果没有金额列，自动计算：**金额 = 数量 × 单价**
- 支持中英文列名模糊匹配

### 2. 支持的分析类型

#### 📊 前N名客户分析 (top_customers)
```python
analyze_excel_data(
    file_path="销售台账.xlsx",
    analysis_type="top_customers",
    top_n=10
)
```
- 自动汇总每个客户的销售额
- 按销售额排序，提取前N名
- 计算销售占比
- 生成美化的Excel报表

#### 🔢 分组聚合分(group_aggregate)
```python
analyze_excel_data(
    file_path="数据.xlsx",
    analysis_type="group_aggregate",
    group_by="产品类别",
    agg_col="销售额",
    agg_func="sum"  # sum/mean/count/max/min
)
```

#### 📈 统计分析 (statistics)
```python
analyze_excel_data(
    file_path="数据.xlsx",
    analysis_type="statistics"
)
```
- 计算平均值、中位数、标准差等
- 自动识别所有数值列

#### 🤖 智能分析 (smart)
```python
analyze_excel_data(
    file_path="数据.xlsx",
    analysis_type="smart",
    question="分析销售额前十的客户"
)
```
- AI自动理解分析需求
- 选择合适的分析方法

## 使用方式

### 在Koto中使用

1. **上传Excel文件到workspace目录**
2. **直接提问**：
   - "分析这个表格，梳理出合计金额前十的客户"
   - "帮我统计一下各个客户的销售额"
   - "生成前10名客户的销售报表"

Koto 会自动：
- 读取Excel文件
- 识别数据结构
- 执行分析
- 生成新的Excel报表
- 返回分析结果

### 示例输出

生成的Excel文件包含：
- ✨ 美观的标题行（蓝色背景，白色加粗文字）
- 📐 自动调整的列宽
- 🔒 冻结的首行
- 📊 格式化的数据（右对齐数字，百分比占比）

```
客户名称                    销售额        销售占比
山东鸿修机械设备有限公司    1,091,119    9.02%
泉州市银合激光科技有限公司    808,030    6.68%
江苏沃飞激光技术有限公司      760,902    6.29%
...
```

## 技术实现

- **文件**: `web/excel_analyzer.py`
- **工具注册**: `web/tool_registry.py` 中的 `analyze_excel_data`
- **依赖**: pandas, openpyxl
- **支持格式**: .xlsx, .xls

## 特性亮点

✅ **无需手动指定列名** - 智能识别客户、金额、数量、单价列  
✅ **自动计算金额** - 如果没有金额列，自动用数量×单价计算  
✅ **美化输出** - 生成专业级Excel报表  
✅ **灵活分析** - 支持多种分析类型和自定义参数  
✅ **中英文支持** - 完全支持中文列名和数据  

## 更新日期

2026-02-12

---

**Enjoy powerful Excel analytics with Koto! 🚀**
