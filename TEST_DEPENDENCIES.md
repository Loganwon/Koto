# 测试依赖说明

## 核心测试（无额外依赖）

以下测试可以在任何安装了基础 requirements.txt 的环境中运行：

```bash
python -m unittest discover -s tests -p "test_phase*.py"
```

**覆盖范围：107 个测试**
- Phase 2 回归测试（agent、工具、路由）
- Phase 3 本地集成测试（SSE、状态管理）
- Phase 4b 监控插件测试
- Phase 4c 脚本生成测试
- Phase 5b 告警插件测试

**依赖：** 仅需 `requirements.txt` 中的核心依赖

---

## 功能测试（需要可选依赖）

功能测试需要额外安装可选依赖包：

### 1. 文档分析测试
**文件：** `tests/test_output_modes.py`  
**依赖：** `google-generativeai`

```bash
pip install google-generativeai
python tests/test_output_modes.py
```

### 2. 文件操作测试
**文件：** `tests/test_file_features.py`  
**依赖：** 无额外依赖

```bash
python tests/test_file_features.py
```

### 3. 主动功能测试
**文件：** `tests/test_proactive_features.py`  
**依赖：** 无额外依赖

```bash
python tests/test_proactive_features.py
```

### 4. 智能功能测试
**文件：** `tests/test_smart_features.py`  
**依赖：** 无额外依赖

```bash
python tests/test_smart_features.py
```

### 5. 路由测试
**文件：** `tests/test_smart_routing.py`  
**依赖：** 无额外依赖

```bash
python tests/test_smart_routing.py
```

---

## E2E 测试（需要 API Key + 网络）

E2E 测试需要真实的 API 密钥和网络连接：

### Agent 端到端测试
**文件：** `tests/test_e2e_agent.py`  
**依赖：** 
- `google-generativeai`
- 配置文件：`config/gemini_config.env` 包含 `GEMINI_API_KEY`
- 网络：可访问 Google AI API

```bash
# 确保 API key 已配置
cat config/gemini_config.env | findstr GEMINI_API_KEY

# 运行 E2E 测试
python tests/test_e2e_agent.py
```

---

## 可选依赖安装

### Web 爬取功能
```bash
pip install beautifulsoup4 lxml
```

### Gemini API 支持
```bash
pip install google-generativeapi
```

### 语音功能（可选）
```bash
pip install -r config/requirements_voice.txt
```

---

## 完整回归测试

运行所有测试（跳过需要 API key 的 E2E 测试）：

```powershell
# 使用标准测试脚本
.\scripts\run_regression.ps1

# 或手动运行
python -m unittest discover -s tests -p "test_phase*.py"
```

**预期结果：** 107/107 tests passing

---

## CI/CD 集成建议

### GitHub Actions 示例

```yaml
- name: Run Core Tests
  run: python -m unittest discover -s tests -p "test_phase*.py" -v

- name: Run Functional Tests (Optional Dependencies)
  run: |
    pip install google-generativeai beautifulsoup4
    python tests/test_file_features.py
    python tests/test_smart_routing.py
  continue-on-error: true

- name: Run E2E Tests (Requires API Key)
  if: ${{ secrets.GEMINI_API_KEY }}
  env:
    GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
  run: python tests/test_e2e_agent.py
  continue-on-error: true
```

---

## 故障排除

### ImportError: No module named 'bs4'
```bash
pip install beautifulsoup4
```

### ImportError: No module named 'google.generativeai'
```bash
pip install google-generativeai
```

### E2E 测试失败："No API key found"
检查 `config/gemini_config.env` 文件是否包含有效的 `GEMINI_API_KEY`

### 测试导入失败
确保从项目根目录运行测试，或测试文件包含正确的 `PROJECT_ROOT` 路径设置
