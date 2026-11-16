# 🚀 Koto 智能文件大脑 - 快速开始指南

## 📋 5分钟快速体验

### 第一步：运行测试
```bash
# 测试所有智能功能
python test_smart_features.py
```

**这将自动**:
- ✅ 创建3个测试文件
- ✅ 提取文件概念（TF-IDF算法）
- ✅ 构建知识图谱（47个节点）
- ✅ 模拟用户行为（6个事件）
- ✅ 生成智能建议（工作模式优化）
- ✅ 创建周报（导出到 workspace/weekly_report.md）

---

### 第二步：启动可视化界面
```bash
# 启动Koto服务器
python web/app.py
```

然后在浏览器中访问：
- **主页**: http://localhost:5000
- **知识图谱**: http://localhost:5000/knowledge-graph

---

### 第三步：体验智能功能

#### 🕸️ 知识图谱可视化
1. 打开 http://localhost:5000/knowledge-graph
2. 看到：
   - 🔵 文件节点（蓝色圆圈）
   - 🟠 概念节点（橙色圆圈）
   - 📏 关联线条（粗细表示相关度）

3. 交互操作：
   - **拖拽节点** - 手动调整布局
   - **悬停节点** - 显示详细信息
   - **点击文件节点** - 加载邻居关系
   - **缩放/平移** - 探索大图谱

4. 侧边栏功能：
   - 查看实时统计
   - 浏览智能建议
   - 查看热门概念
   - 生成周报

---

## 🛠️ API 使用指南

### 1. 概念提取 API

#### 提取文件概念
```bash
curl -X POST http://localhost:5000/api/concepts/extract \
  -H "Content-Type: application/json" \
  -d '{"file_path": "workspace/test_ai.txt", "top_n": 10}'
```

**返回**:
```json
{
  "file_path": "workspace/test_ai.txt",
  "concepts": [
    {"concept": "机器学习", "score": 0.0417},
    {"concept": "深度学习", "score": 0.0417}
  ],
  "analyzed_at": "2026-02-15T20:40:00"
}
```

#### 查找相关文件
```bash
curl -X POST http://localhost:5000/api/concepts/related-files \
  -H "Content-Type: application/json" \
  -d '{"file_path": "workspace/test_ai.txt", "limit": 5}'
```

**返回**:
```json
{
  "success": true,
  "related_files": [
    {
      "file_path": "workspace/test_python.txt",
      "similarity": 0.3162,
      "shared_concepts": ["机器学习", "Python"]
    }
  ]
}
```

---

### 2. 知识图谱 API

#### 构建图谱
```bash
curl -X POST http://localhost:5000/api/knowledge-graph/build \
  -H "Content-Type: application/json" \
  -d '{
    "file_paths": [
      "workspace/test_ai.txt",
      "workspace/test_python.txt",
      "workspace/test_web.txt"
    ],
    "force_rebuild": false
  }'
```

#### 获取图谱数据（用于D3.js）
```bash
curl http://localhost:5000/api/knowledge-graph/data?max_nodes=100
```

**返回**:
```json
{
  "nodes": [
    {
      "id": "file:workspace/test_ai.txt",
      "type": "file",
      "label": "test_ai.txt",
      "metadata": {}
    },
    {
      "id": "concept:机器学习",
      "type": "concept",
      "label": "机器学习",
      "metadata": {"score": 0.0417}
    }
  ],
  "edges": [
    {
      "source": "file:workspace/test_ai.txt",
      "target": "concept:机器学习",
      "type": "contains",
      "weight": 0.0417
    }
  ]
}
```

---

### 3. 行为监控 API

#### 记录用户操作
```bash
curl -X POST http://localhost:5000/api/behavior/log-event \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "file_open",
    "file_path": "workspace/test_ai.txt",
    "duration_ms": 5000
  }'
```

#### 获取最常用文件
```bash
curl http://localhost:5000/api/behavior/top-files?limit=10
```

**返回**:
```json
{
  "success": true,
  "files": [
    {
      "file_path": "workspace/test_ai.txt",
      "open_count": 5,
      "edit_count": 2,
      "usage_score": 9
    }
  ]
}
```

#### 工作模式分析
```bash
curl http://localhost:5000/api/behavior/work-patterns
```

**返回**:
```json
{
  "time_of_day": [
    {"period": "evening", "frequency": 25},
    {"period": "afternoon", "frequency": 18}
  ],
  "operation_types": [
    {"operation": "file_edit", "frequency": 42},
    {"operation": "file_search", "frequency": 15}
  ]
}
```

---

### 4. 智能建议 API

#### 生成建议
```bash
curl -X POST http://localhost:5000/api/suggestions/generate \
  -H "Content-Type: application/json" \
  -d '{"force_regenerate": true}'
```

**返回**:
```json
{
  "success": true,
  "suggestions": [
    {
      "id": 1,
      "type": "organize",
      "title": "建议整理 workspace 目录",
      "description": "该目录下有 5 个常用文件，建议创建子文件夹进行分类整理。",
      "priority": "medium",
      "action_items": [
        {
          "label": "自动分类",
          "action": "auto_organize"
        }
      ]
    }
  ]
}
```

#### 应用建议
```bash
curl -X POST http://localhost:5000/api/suggestions/apply \
  -H "Content-Type: application/json" \
  -d '{"suggestion_id": 1, "feedback": "很有帮助"}'
```

---

### 5. 洞察报告 API

#### 生成周报
```bash
curl -X POST http://localhost:5000/api/insights/generate-weekly
```

**返回**:
```json
{
  "success": true,
  "report": {
    "type": "weekly",
    "period": {
      "start": "2026-02-08T00:00:00",
      "end": "2026-02-15T00:00:00",
      "days": 7
    },
    "sections": {
      "activity_overview": {
        "total_events": 42,
        "daily_average": 6.0,
        "active_days": 5
      },
      "productivity": {
        "productivity_score": 66.7,
        "interpretation": "高效 - 你专注于创造内容"
      }
    },
    "summary_markdown": "# 📊 Koto 工作报告\n\n..."
  }
}
```

#### 导出Markdown
```bash
curl -X POST http://localhost:5000/api/insights/export-markdown \
  -H "Content-Type: application/json" \
  -d '{
    "report": {...},
    "output_path": "workspace/my_report.md"
  }'
```

---

## 💡 使用场景示例

### 场景1：新项目启动

```python
from web.knowledge.concept_extractor import ConceptExtractor
from web.knowledge.knowledge_graph import KnowledgeGraph

# 1. 索引项目文件
extractor = ConceptExtractor()
files = ["docs/design.md", "src/main.py", "README.md"]

for file in files:
    result = extractor.analyze_file(file)
    print(f"提取了 {len(result['concepts'])} 个概念")

# 2. 构建项目知识图谱
kg = KnowledgeGraph()
kg.build_file_graph(files)

# 3. 查看项目核心概念
top_concepts = extractor.get_top_concepts(limit=10)
print("项目关键概念:", [c['concept'] for c in top_concepts])
```

---

### 场景2：查找相关文档

```python
# 正在阅读一个文件，想找相关资料
current_file = "docs/api_design.md"

extractor = ConceptExtractor()
related = extractor.find_related_files(current_file, limit=5)

print("相关文档推荐:")
for item in related:
    print(f"  • {item['file_path']}")
    print(f"    相似度: {item['similarity']:.1%}")
    print(f"    共享概念: {', '.join(item['shared_concepts'])}")
```

---

### 场景3：周报生成

```python
from web.knowledge.insight_reporter import InsightReporter

reporter = InsightReporter()

# 生成本周工作报告
report = reporter.generate_weekly_report()

# 导出Markdown
reporter.export_report_markdown(report, "周报_2026W07.md")

# 查看关键指标
print(f"本周完成 {report['sections']['activity_overview']['total_events']} 次操作")
print(f"生产力评分: {report['sections']['productivity']['productivity_score']}%")
```

---

### 场景4：实时建议

```python
from web.proactive.suggestion_engine import SuggestionEngine

engine = SuggestionEngine()

# 生成智能建议
suggestions = engine.generate_suggestions()

# 显示高优先级建议
high_priority = [s for s in suggestions if s['priority'] == 'high']
for suggestion in high_priority:
    print(f"🔴 {suggestion['title']}")
    print(f"   {suggestion['description']}")
    
    # 应用建议
    if input("要应用这个建议吗? (y/n): ") == 'y':
        engine.apply_suggestion(suggestion['id'])
```

---

## 🎨 自定义规则

### 添加自定义建议规则

```python
from web.proactive.suggestion_engine import SuggestionEngine

# 继承并扩展
class CustomSuggestionEngine(SuggestionEngine):
    def __init__(self):
        super().__init__()
        # 添加自定义规则
        self.rules.append(self._rule_custom_check)
    
    def _rule_custom_check(self):
        """自定义规则：检测特定条件"""
        suggestions = []
        
        # 获取数据
        files = self.behavior_monitor.get_frequently_used_files(limit=100)
        
        # 自定义逻辑
        large_files = [f for f in files if f.get('size', 0) > 10*1024*1024]  # 大于10MB
        
        if len(large_files) >= 5:
            suggestions.append({
                "type": "optimize",
                "title": "发现多个大文件",
                "description": f"有 {len(large_files)} 个文件超过10MB，建议压缩或归档。",
                "priority": "medium",
                "context": {"files": [f['file_path'] for f in large_files]},
                "action_items": [
                    {"label": "查看详情", "action": "show_large_files"},
                    {"label": "一键压缩", "action": "compress_files"}
                ]
            })
        
        return suggestions

# 使用
engine = CustomSuggestionEngine()
suggestions = engine.generate_suggestions()
```

---

## 🔧 配置选项

### 修改数据库路径

```python
from web.knowledge.concept_extractor import ConceptExtractor
from web.knowledge.knowledge_graph import KnowledgeGraph

# 自定义数据库位置
extractor = ConceptExtractor(db_path="data/my_concepts.db")
kg = KnowledgeGraph(db_path="data/my_graph.db")
```

### 调整性能参数

```python
# 提取更多概念
extractor.extract_concepts(text, top_n=20)  # 默认10

# 增加图谱节点数
graph_data = kg.get_graph_data(max_nodes=500)  # 默认100

# 查询更深的邻居
neighbors = kg.get_file_neighbors(file_path, depth=2)  # 默认1
```

---

## 📊 监控与调试

### 查看系统统计

```python
from web.knowledge.concept_extractor import ConceptExtractor
from web.knowledge.knowledge_graph import KnowledgeGraph
from web.behavior_monitor import BehaviorMonitor
from web.proactive.suggestion_engine import SuggestionEngine

# 概念提取统计
extractor = ConceptExtractor()
print("概念提取:", extractor.get_statistics())

# 知识图谱统计
kg = KnowledgeGraph()
print("知识图谱:", kg.get_statistics())

# 行为监控统计
monitor = BehaviorMonitor()
print("行为监控:", monitor.get_statistics())

# 建议引擎统计
engine = SuggestionEngine()
print("建议引擎:", engine.get_statistics())
```

**输出示例**:
```
概念提取: {
    'total_files_analyzed': 150,
    'total_unique_concepts': 1248,
    'total_concept_relations': 2890,
    'avg_concepts_per_file': 19.3
}

知识图谱: {
    'total_files': 150,
    'total_concepts': 1248,
    'file_concept_edges': 2890,
    'file_relation_edges': 342,
    'average_degree': 21.2,
    'graph_density': 0.015
}

行为监控: {
    'total_events': 1542,
    'total_files_tracked': 89,
    'total_searches': 127,
    'most_common_operation': 'file_edit',
    'last_7_days_events': 284
}

建议引擎: {
    'total_suggestions': 23,
    'pending_suggestions': 5,
    'applied_suggestions': 12,
    'dismissed_suggestions': 6,
    'acceptance_rate': 66.67
}
```

---

## 🐛 常见问题

### Q1: 中文分词不准确？
**A**: 安装 jieba 分词库：
```bash
pip install jieba
```

### Q2: 图谱构建很慢？
**A**: 使用增量更新，不要每次都 force_rebuild：
```python
kg.build_file_graph(files, force_rebuild=False)  # 只处理新文件
```

### Q3: 建议总是相同？
**A**: 建议有缓存机制，使用 force_regenerate：
```python
suggestions = engine.generate_suggestions(force_regenerate=True)
```

### Q4: 如何清空数据？
**A**: 删除数据库文件：
```bash
rm config/concepts.db
rm config/knowledge_graph.db
rm config/user_behavior.db
rm config/suggestions.db
rm config/insights.db
```

---

## 🎯 下一步

1. ✅ 运行 `test_smart_features.py` 验证功能
2. ✅ 启动 Web 界面体验可视化
3. ✅ 索引你的真实项目文件
4. ✅ 阅读 [完整实现文档](SMART_FEATURES_IMPLEMENTATION.md)
5. ✅ 自定义规则和建议

---

**祝你使用愉快！** 🎉

有问题随时查看文档或提issue。
