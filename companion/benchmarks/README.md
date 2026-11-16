# 真实文件与开源 Agent 横向比较

比较对象：当前 Koto / Deep Agents、上游 Pi Agent Core、上游
smolagents.ToolCallingAgent。三者共用 Koto 的文件工具、写入核对器、任务账本、
请求和输入副本，比较执行流程。不是完整产品排名，也不代表任意电脑操作能力。

运行前需要已安装的 `.venv-agent`、Pi npm 依赖，以及隔离的
`.venv-agent-bench`（本目录 requirements.txt）。比较依赖不进入生产环境。

```powershell
.venv/Scripts/python.exe -m companion.benchmarks.run --root .pytest_tmp/my-comparison --freeze
.venv/Scripts/python.exe -m companion.benchmarks.grade --root .pytest_tmp/my-comparison
```

`--freeze` 生成不可覆盖的输入副本、真实请求和实现校验值。
默认从用户桌面的 DS_KEY.txt 读取已授权测试密钥，密钥不通过命令参数传递。
运行会调用真实 API 并产生计费；报告、事件和交付物保存在指定测试目录。
`--engines` / `--cases` 可缩小范围。已有运行目录不会被覆盖或自动替换。

四类任务：全量销售核算、无规则表头财务矩阵、DOCX/PDF/PPTX 联合交付与
只读追问/反馈改向、单段修改后暂停。前三类使用 workspace 真实文件副本；
最后一类使用 JsonDocument 编辑夹具，必须与原生 Office / WPS 验收分开。

每轮执行预算为60次循环模型请求、100次工具调用、240秒；写入语义核对和
最多两次局部草稿修复另记事件。当前修复建议不会自动发布，仍走原工具与核对。
原文件 SHA256、逐行数据、金额整数分、16个财务坐标和实际 OOXML 字数由
独立读取器验收；不采用模型自报成功率或自报字数。

验收允许等价展示：OOXML浮点序列化误差、数字后的已声明单位、百分数字符串、
季度表附加合计/说明行。原始文本/空值/整数分保持精确，计数上限不放宽。
每类一次运行属于小样本；失败和中间复测均保留，不能用挑选成功替换原记录。
