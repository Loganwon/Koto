# ppt, pptx, 幻灯片, 演示, 总结页, 新增页, 添加页, slide, presentation
# Skill: PowerPoint 操作

## 关键原则

- 用 `TASK_SANDBOX_FILE_PATHS['文件.pptx']` **读取**（沙盒副本，安全）
- 用 `TASK_FILE_PATHS['文件.pptx']` **保存**（工作区原文件，必须）
- 修改后必须打印 `KOTO_MODIFIED:` + 原文件路径
- 新建文件打印 `KOTO_CREATED:` + 绝对路径
- 如果用户要求“美化 / 好看 / 漂亮 / 专业 / 高级 / 统一视觉 / 排版 / 主题 / 版式”，必须做真实 PPTX 设计写回，不能只给设计建议。
- 美化已有 PPT 时默认保留原页数、原文字和核心内容；除非用户明确要求新增、删除或重写页面。
- 完成后必须核验：页数、标题/正文是否仍存在、是否产生真实修改标记、是否有布局拥挤或文本过长提示。

## 高质量 PPT 编辑标准

1. **先读原稿**：确认总页数、每页标题、正文密度和明显风险，不要盲目覆盖。
2. **内容先行**：如果需要改写或新增页面，先完成内容写回，再统一设计。
3. **视觉系统**：统一字体、标题层级、正文大小、背景、强调色和页码/装饰元素；避免每页随机风格。
4. **安全版式**：标题和正文使用稳定网格，避免文字压边、遮挡、过密或跑出版面。
5. **结果核验**：报告设计页数、主题名、布局策略、是否保留页数，以及任何需要人工复核的页面。

## 推荐原生工具路线

- 更新现有页文字：`write_pptx_slides`
- 新增总结页/补充页：`add_pptx_slides`
- 美化、统一主题和版式：`design_pptx_theme_layout`
- 高质量编辑通常是：读取 PPTX → 写文字/新增页 → `design_pptx_theme_layout` → 核验结果

## 读取 PPT 内容

```python
from pptx import Presentation

src = TASK_SANDBOX_FILE_PATHS['AI Agent.pptx']
prs = Presentation(src)
print(f'共 {len(prs.slides)} 页')
for i, slide in enumerate(prs.slides, 1):
    texts = []
    for shape in slide.shapes:
        if shape.has_text_frame:
            for para in shape.text_frame.paragraphs:
                t = para.text.strip()
                if t:
                    texts.append(t)
    print(f'--- 第 {i} 页 ---')
    print('\n'.join(texts[:6]))
```

## 在末尾追加新幻灯片

```python
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN

src  = TASK_SANDBOX_FILE_PATHS['演示.pptx']
dest = TASK_FILE_PATHS['演示.pptx']   # ← 写回工作区原文件
prs  = Presentation(src)

slide_layout = prs.slide_layouts[1]   # Title and Content
slide = prs.slides.add_slide(slide_layout)

# 设置标题
slide.shapes.title.text = '总结'
slide.shapes.title.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER

# 设置内容
body = slide.placeholders[1]
tf   = body.text_frame
tf.text = '第一要点'
for point in ['第二要点', '第三要点']:
    p = tf.add_paragraph()
    p.text = point
    p.level = 0

prs.save(dest)
print('KOTO_MODIFIED:' + dest)
print(f'保存完毕，现共 {len(prs.slides)} 页')
```

## 批量修改文字

```python
from pptx import Presentation

src  = TASK_SANDBOX_FILE_PATHS['演示.pptx']
dest = TASK_FILE_PATHS['演示.pptx']
prs  = Presentation(src)

for slide in prs.slides:
    for shape in slide.shapes:
        if shape.has_text_frame:
            for para in shape.text_frame.paragraphs:
                for run in para.runs:
                    run.text = run.text.replace('旧词', '新词')

prs.save(dest)
print('KOTO_MODIFIED:' + dest)
```

## 复制幻灯片（跨文件）

```python
from pptx import Presentation
from pptx.oxml.ns import qn
from lxml import etree
import copy

src_path  = TASK_SANDBOX_FILE_PATHS['源文件.pptx']
dest_path = TASK_FILE_PATHS['目标文件.pptx']

src_prs  = Presentation(src_path)
dest_prs = Presentation(dest_path)

# 复制第 N 页到末尾
slide_to_copy = src_prs.slides[0]  # 改成需要的索引
xml_copy = copy.deepcopy(slide_to_copy._element)
dest_prs.slides._sldIdLst.append(etree.fromstring('<p:sldId xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" id="999" r:id="rId99" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>'))
dest_prs.slides._sldIdLst[-1].set(qn('r:id'), dest_prs.part.relate_to(
    dest_prs.slide_master.slide_layouts[0].part, 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide'))

dest_prs.save(dest_path)
print('KOTO_MODIFIED:' + dest_path)
```

## 注意事项

- **保存路径必须是 `TASK_FILE_PATHS[...]`**，不能保存到 `TASK_SANDBOX_FILE_PATHS` 否则修改会丢失
- 原生工具已支持对 PPTX 做统一主题、字体、配色和安全版式处理；复杂图片/图表内容仍建议谨慎处理
- 如需插入图片：`slide.shapes.add_picture(img_path, left, top, width, height)`
- 添加文本框：`slide.shapes.add_textbox(left, top, width, height)`
