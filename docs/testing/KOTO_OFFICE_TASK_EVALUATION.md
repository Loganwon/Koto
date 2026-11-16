# 固定办公任务验收

此验收集包含24个固定任务：读材料、修改现有文件、生成后追改、故障与恢复各6个。它运行生产FileTaskRuntime、Kernel、工具和持久化代码，使用脚本模型控制工具决策。结果是受控模型下的工程任务通过率，不能解释为真实模型质量、真实浏览器成功率或将单测数量换算成任务成功率。

评分重新打开最终文件，检查材料数字与来源、文本精确范围、Word原段落/表格/标题/页眉样式、Excel非目标单元格与公式样式、PPT原页面与主题、生成文件数量及重复追加。故障任务要求正确拒绝并保留原文件；恢复任务必须沿用持久回执且不重复写入。安全备份仅允许精确的预期文件名加`.bak`，另存副本仍判失败。

使用项目虚拟环境；每次选择新的状态目录，脚本不会清理或覆盖先前证据：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B scripts/standalone_office_eval.py --state-dir build/office-evaluation-fixture-run --repeats 3
```

默认每项重复3次，共72次。`evaluation.md`和`evaluation.json`记录逐项通过情况、运行时耗时、模型/工具调用、模型事件TTFT，以及任务文本和验收代码哈希。`results/`保存原始事件和逐条规则；`workspace/`保存合成材料与实际最终文件。运行期间生产源码变化会明确使本次版本证据失效。耗时包含首次运行时导入；fixture TTFT只反映框架与脚本回调，不能代表模型推理性能。

Provider没有报告的token保持`null`，上下文预算估算单独记录，不能作为计费事实。fixture没有真实provider计费用量。

真实连接探针单独执行，必须在fixture隔离前启动，且只读取当前已配置provider：

```powershell
.\.venv\Scripts\python.exe -B scripts/office_live_probe.py --output build/office-evaluation-live/live-probe.json
```

探针限制1次请求、输出最多16token、SDK超时6秒、父进程总期限12秒，关闭SDK和provider重试。已有探针报告直接复用。只输出provider/model/host、错误类型与数值错误码、真实usage；不输出凭据、请求头、异常原文或模型正文。连接阻塞后停止live组，实际办公任务次数为0，费用与用量保持不可得。安全连通后，必须另外配置实际任务的请求次数、输入/输出token和总耗时硬预算，不能把一次连通当成办公质量通过。

可将已有的脱敏探针报告附入工程验收报告；此参数不会发起网络请求：

```powershell
.\.venv\Scripts\python.exe -B scripts/standalone_office_eval.py --state-dir build/office-evaluation-fixture-final --repeats 3 --live-probe-report build/office-evaluation-live/live-probe.json
```

真实浏览器验收使用现有HTTP入口。无法访问时记录环境阻塞，不通过本地文件、假后端或自动化脚本绕过浏览器策略。
