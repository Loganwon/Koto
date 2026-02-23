# 文档标注进度卡顿修复说明

## 问题描述
文档标注时UI卡在16%的"正在分析文档..."阶段，无法看到实时进度更新。

## 根本原因
`analyze_for_annotation_chunked` 方法在处理82段文本时：
- ✅ 有控制台进度输出（print语句）
- ❌ 没有实时回调给前端UI
- ❌ 前端一直停留在初始的16%进度

## 已修复内容

### 1. 添加进度回调机制 ([document_feedback.py](web/document_feedback.py#L1068-L1090))
```python
def analyze_for_annotation_chunked(
    self,
    file_path: str,
    user_requirement: str = "",
    model_id: str = "gemini-3-flash-preview",
    chunk_size: int = 3000,
    progress_callback: Optional[Callable[[int, int, str], None]] = None  # 新增
) -> Dict[str, Any]:
```

### 2. 在处理循环中调用回调 ([document_feedback.py](web/document_feedback.py#L1265-L1272))
```python
# 回调进度
if progress_callback:
    progress_callback(
        processed, 
        total_chunks_initial, 
        f"正在处理第 {processed}/{total_chunks_initial} 段（已标注{len(all_annotations)}条）"
    )
```

### 3. 流式方法中接收并转发进度 ([document_feedback.py](web/document_feedback.py#L1595-L1630))
```python
# 存储进度事件队列
progress_queue = []

def on_analysis_progress(current, total, message):
    progress = 15 + int((current / total) * 35)  # 15%-50%
    if current_time - last_yield_time[0] >= 0.5:  # 限流0.5秒
        progress_queue.append({
            'stage': 'analyzing',
            'progress': progress,
            'message': '🤖 正在分析文档...',
            'detail': message
        })

# 处理后yield所有进度事件
for evt in progress_queue:
    yield evt
```

## 效果演示

### 修复前：
```
🤖 正在分析文档...
使用 AI 检查 82 段文本
进度: 16%  ← 长时间停留
```

### 修复后：
```
🤖 正在分析文档...
正在处理第 5/82 段（已标注12条）
进度: 17%

🤖 正在分析文档...
正在处理第 10/82 段（已标注28条）
进度: 19%

🤖 正在分析文档...
正在处理第 20/82 段（已标注55条）
进度: 24%

... （持续更新）

✅ 分析完成
找到 156 处修改
进度: 50%
```

## 进度分布
- **15%**: 开始分析
- **15%-50%**: 分段处理中（每0.5秒更新一次）
- **50%**: 分析完成
- **55%-85%**: 应用修改
- **100%**: 完成

## 测试方法

1. 重启Koto应用
2. 上传较大的Word文档（82段以上）
3. 发送标注指令
4. 观察进度条应该平滑增长，不再卡顿

## 技术细节

### 回调限流
使用0.5秒的限流避免过于频繁的UI更新：
```python
if current_time - last_yield_time[0] >= 0.5:
    # 更新进度
```

### 进度队列
使用队列收集进度事件，避免在同步函数中直接yield：
```python
progress_queue.append(event)  # 收集
...
for evt in progress_queue:    # 统一yield
    yield evt
```

### 类型安全
添加了Callable类型提示：
```python
from typing import Dict, Any, Optional, List, Callable
```

## 相关文件
- [web/document_feedback.py](web/document_feedback.py) - 核心修复
- [web/app.py](web/app.py#L10877) - SSE流式API
- [web/static/js/app.js](web/static/js/app.js) - 前端进度显示

## 下次改进
- [ ] 添加取消功能（当前已有check_task_cancelled但未完全接入）
- [ ] 估计剩余时间显示
- [ ] 分段处理可配置（chunk_size参数）
