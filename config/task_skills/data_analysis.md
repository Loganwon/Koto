# 图表, chart, 分析, 可视化, 统计, 趋势, 对比
# Skill: 数据分析与图表生成

## 常见任务模式

### 数据分析 + 图表
1. 用 `read_sheet_data` 或 `parse_file_to_text` 获取数据
2. 用 `run_python_code` 编写 pandas 分析 + matplotlib 图表代码
3. 图表会保存到沙盒，返回给用户

### Python 代码模板
```python
import pandas as pd
import matplotlib.pyplot as plt
plt.rcParams['font.sans-serif'] = ['SimHei']  # 中文支持
plt.rcParams['axes.unicode_minus'] = False

# 读取数据
df = pd.read_excel('/path/to/file.xlsx')

# 分析 & 绘图
fig, ax = plt.subplots(figsize=(10, 6))
# ... 绘图代码 ...
plt.tight_layout()
plt.savefig('output.png', dpi=150)
plt.show()
```

## 注意事项
- matplotlib 中文需要设置 SimHei 字体
- 优先用 pandas 读取，避免手动解析
- 图表输出为 PNG，会被沙盒捕获返回
