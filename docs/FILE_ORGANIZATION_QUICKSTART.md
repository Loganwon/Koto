# 🚀 Koto 文件组织系统 - 快速使用指南

## 概述

Koto 文件组织系统是一个智能文件分类和自动归纳工具，类似于腾讯IMA的功能。它能够：

✅ **自动分析文件内容** - 识别文件的行业、类型、时间等属性  
✅ **智能分类组织** - 将文件自动放入对应的文件夹  
✅ **快速搜索检索** - 按行业、关键词、时间搜索文件  
✅ **统计信息展示** - 显示文件组织的详细统计  

---

## 快速开始 (3步)

### 1️⃣ 启动 Koto 应用

进入脚本目录并启动应用：

```bash
cd C:\Users\12524\Desktop\Koto\scripts
.\run_desktop.bat
```

或使用PowerShell：

```powershell
cd "C:\Users\12524\Desktop\Koto\scripts"
.\run_desktop.ps1
```

应用启动后会自动打开浏览器，访问: **http://localhost:5000**

### 2️⃣ 测试文件分析功能

运行本地测试脚本，查看系统如何分析和组织示例文件：

```bash
cd C:\Users\12524\Desktop\Koto
python test_file_organization.py
```

### 3️⃣ 查看完整演示

运行功能演示脚本，了解所有功能：

```bash
cd C:\Users\12524\Desktop\Koto
python demo_file_organization.py
```

---

## 核心功能详解

### 🔍 文件分析 (FileAnalyzer)

**位置**: `app/core/services/file_analyzer.py`

**功能**: 分析文件内容，识别：

| 属性 | 说明 | 示例 |
|------|------|------|
| 行业 | 5种行业分类 | finance, medical, property, education, projects |
| 类别 | 细粒度分类 | contract, record, plan, course, lease |
| 时间 | 年月或年季度 | 2026-01, 2026-Q1 |
| 主题 | 具体主题标签 | 融资, 检查, 租赁, 课程, 计划 |
| 文件类型 | 文件格式 | .txt, .pdf, .docx, .xlsx |

**支持的文件格式**:
- 纯文本: `.txt`
- 数据格式: `.json`, `.csv`, `.log`
- 文档格式: `.pdf`, `.docx`, `.xlsx` (仅当安装对应库时)

**使用示例**:

```python
from web.file_analyzer import FileAnalyzer

analyzer = FileAnalyzer()
result = analyzer.analyze_file("your_file.txt")

print(result['industry'])        # finance
print(result['category'])        # contract
print(result['suggested_folder']) # finance/2026/Q1/Contract/融资
```

---

### 📁 文件组织 (FileOrganizer)

**位置**: `app/core/services/file_organizer.py`

**功能**: 根据分析结果，自动创建文件夹并组织文件

**文件夹结构**:

```
workspace/_organize/
├── {industry}/           # 行业
│   ├── {year}/          # 年份
│   │   ├── {quarter}/   # 季度 (Q1-Q4)
│   │   │   ├── {category}/  # 分类
│   │   │   │   ├── {subject}/  # 主题
│   │   │   │   │   └── file.txt
```

**示例**:
```
finance/2026/Q1/Contract/融资/contract_001.txt
medical/2025/Q4/Record/检查/checkup_2025.pdf
property/2026/Q0/Lease/租赁/apartment_lease.docx
```

**使用示例**:

```python
from web.file_organizer import FileOrganizer

organizer = FileOrganizer("workspace/_organize")

# 单个文件组织
result = organizer.organize_file(
    source_file="document.txt",
    suggested_folder="finance/2026/Q1/Contract/融资",
    auto_confirm=True
)

# 批量文件组织
files = [
    {"file": "file1.txt", "folder": "finance/2026/Q1/..."},
    {"file": "file2.txt", "folder": "medical/2026/Q1/..."},
]
results = organizer.organize_batch(files)

# 搜索
results = organizer.search_files("合同")

# 统计
stats = organizer.get_categories_stats()
folders = organizer.list_organized_folders()
```

---

### 🌐 API 接口

**集成位置**: `web/app.py` (第11020+ 行)

#### POST /api/organize/scan-file
分析单个文件

**请求**:
```bash
curl -X POST http://localhost:5000/api/organize/scan-file \
  -H "Content-Type: application/json" \
  -d '{"file_path": "C:\\path\\to\\file.txt"}'
```

**响应**:
```json
{
  "success": true,
  "file": "contract.txt",
  "analysis": {
    "industry": "finance",
    "category": "contract",
    "timestamp": "2026-01",
    "suggested_folder": "finance/2026/Q1/Contract/融资"
  }
}
```

#### POST /api/organize/auto-organize
分析并自动组织文件

**请求**:
```bash
curl -X POST http://localhost:5000/api/organize/auto-organize \
  -H "Content-Type: application/json" \
  -d '{
    "file_path": "C:\\path\\to\\file.txt",
    "auto_confirm": true
  }'
```

**响应**:
```json
{
  "success": true,
  "file": "contract.txt",
  "organized": {
    "source_file": "C:\\...",
    "dest_file": "C:\\...\\workspace\\_organize\\...",
    "relative_path": "finance/2026/Q1/Contract/融资/contract.txt"
  }
}
```

#### GET /api/organize/list-categories
列出所有分类和文件夹

**请求**:
```bash
curl http://localhost:5000/api/organize/list-categories
```

**响应**:
```json
{
  "success": true,
  "folders": {
    "finance/2026/Q1/Contract/融资": {
      "file_count": 3,
      "files": ["contract1.txt", "contract2.txt"]
    }
  },
  "stats": {...}
}
```

#### POST /api/organize/search
搜索已组织的文件

**请求**:
```bash
curl -X POST http://localhost:5000/api/organize/search \
  -H "Content-Type: application/json" \
  -d '{"keyword": "合同"}'
```

**响应**:
```json
{
  "success": true,
  "keyword": "合同",
  "count": 2,
  "results": [
    {
      "file_name": "contract1.txt",
      "folder": "finance/2026/Q1/Contract/融资"
    }
  ]
}
```

#### GET /api/organize/stats
获取统计信息

**请求**:
```bash
curl http://localhost:5000/api/organize/stats
```

**响应**:
```json
{
  "success": true,
  "total_files": 15,
  "total_folders": 8,
  "by_industry": {
    "finance": {"count": 5, "size": 25600},
    "medical": {"count": 3, "size": 15360}
  },
  "last_updated": "2026-02-13T12:04:35"
}
```

---

## 高级使用

### 自定义分类规则

编辑 `app/core/services/file_analyzer.py` 中的分类规则：

```python
# 修改行业关键字
INDUSTRY_KEYWORDS = {
    'finance': ['合同', '融资', '利率', ...],
    'medical': ['医疗', '患者', '病历', ...],
    # 添加新的行业
    'custom_industry': ['keyword1', 'keyword2', ...]
}

# 修改分类规则
CATEGORY_KEYWORDS = {
    'finance': {
        'contract': ['合同', '协议', ...],
        'report': ['报告', '汇总', ...],
        'custom': ['...']
    }
}
```

### 批量导入文件

创建Python脚本，批量处理文件：

```python
from web.file_analyzer import FileAnalyzer
from web.file_organizer import FileOrganizer
from pathlib import Path

analyzer = FileAnalyzer()
organizer = FileOrganizer("workspace/_organize")

# 扫描文件夹
source_dir = Path("path/to/files")
for file_path in source_dir.glob("**/*"):
    if file_path.is_file():
        # 分析
        analysis = analyzer.analyze_file(str(file_path))
        
        if analysis.get('success'):
            # 组织
            organizer.organize_file(
                str(file_path),
                analysis['suggested_folder'],
                auto_confirm=True
            )
            print(f"✅ {file_path.name}")
```

---

## 📊 统计和报告

### 查看组织结果

查看 `workspace/_organize/` 目录结构：

```
workspace/_organize/
├── index.json          (全局文件索引)
├── finance/
│   ├── 2026/Q1/Contract/融资/
│   │   ├── contract1.txt
│   │   └── _metadata.json
├── medical/
│   └── ...
└── ...
```

### 查看索引文件

`workspace/_organize/index.json` 包含所有文件的元数据：

```json
{
  "version": "1.0",
  "total_files": 15,
  "files": [
    {
      "file_name": "contract.txt",
      "source_path": "C:\\path\\contract.txt",
      "organized_path": "C:\\...\\workspace\\_organize\\finance\\...",
      "folder": "finance/2026/Q1/Contract/融资",
      "file_size": 1024,
      "organized_at": "2026-02-13T12:04:35"
    }
  ]
}
```

---

## 🔧 配置和定制

### 修改默认路径

在 `web/app.py` 中修改 `get_file_organizer()` 函数：

```python
def get_file_organizer():
    if 'organizer' not in _file_organizer_cache:
        from file_organizer import FileOrganizer
        
        ws_root = get_workspace_root()
        # 修改此行改变组织路径
        organize_root = os.path.join(ws_root, "custom_organize_folder")
        _file_organizer_cache['organizer'] = FileOrganizer(organize_root)
    
    return _file_organizer_cache['organizer']
```

### 添加新的行业分类

编辑 `app/core/services/file_analyzer.py`：

```python
CLASSIFICATION_RULES = {
    'new_industry': {
        'keywords': ['keyword1', 'keyword2'],
        'categories': {
            'new_category': {
                'keywords': ['keyword1', 'keyword2'],
                'subjects': ['subject1', 'subject2']
            }
        }
    }
}
```

---

## 🐛 故障排除

### 问题1: 文件未被正确分类

**原因**: 关键词匹配不准确
**解决**: 
1. 检查 `app/core/services/file_analyzer.py` 中的关键词
2. 在演示中观察分析结果的置信度
3. 手动调整分类规则

### 问题2: API无法连接

**原因**: Koto应用未启动或端口被占用
**解决**:
1. 检查 Koto 是否正在运行
2. 检查是否有其他应用占用5000端口
3. 查看 Koto 的启动日志

### 问题3: 文件夹创建失败

**原因**: 路径包含非法字符或权限不足
**解决**:
1. 检查文件名和路径是否包含非法字符
2. 确保对 `workspace/` 目录有写入权限
3. 检查 `workspace/_organize/` 目录是否存在

---

## 📚 更多资源

- **设计文档**: `docs/FILE_ORGANIZATION_DESIGN.md`
- **测试报告**: `TEST_RESULTS_REPORT.md`
- **源代码**: 
  - `app/core/services/file_analyzer.py` - 分析引擎
  - `app/core/services/file_organizer.py` - 组织引擎
  - `web/app.py` - API 接口
- **测试脚本**:
  - `test_file_organization.py` - 完整测试
  - `demo_file_organization.py` - 功能演示

---

## 📞 支持

如有问题，请查看：
1. 日志文件: `logs/` 目录
2. 测试结果: `TEST_RESULTS_REPORT.md`
3. 演示脚本输出: 运行 `python demo_file_organization.py`

---

**版本**: 1.0  
**最后更新**: 2026-02-13  
**状态**: 🚀 生产就绪
