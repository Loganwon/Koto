import os
from app.core.tools.user_tool_loader import koto_tool

@koto_tool(
    description="转换文件格式为目标格式。支持场景：\n1. 图像互转 (如 png/jpg/webp/bmp/gif)\n2. 数据/表格互转 (csv/xlsx/json)\n3. 文档处理 (pdf转txt、docx转txt)。如果需要 pdf转docx 或 docx转pdf，会提示缺少库或尝试转换。",
    parameters={
        "source_path": {"type": "STRING", "description": "要转换的源文件相对路径或绝对路径"},
        "target_format": {"type": "STRING", "description": "目标文件后缀名，例如 'png', 'jpg', 'csv', 'xlsx', 'txt', 'docx', 'pdf'"},
        "dest_path": {"type": "STRING", "description": "（可选）目标文件保存路径。如果是空，则自动在原目录下生成 '_converted' 为后缀的新文件。"}
    },
    required=["source_path", "target_format"]
)
def convert_file_format(source_path: str, target_format: str, dest_path: str = "") -> str:
    """实用文件格式转换工具"""
    try:
        source_path = os.path.abspath(source_path)
        if not os.path.exists(source_path):
            return f"❌ 转换失败：未找到源文件 '{source_path}'"
        
        target_format = target_format.lower().strip('.')
        if not dest_path:
            base, _ = os.path.splitext(source_path)
            dest_path = f"{base}_converted.{target_format}"
        else:
            dest_path = os.path.abspath(dest_path)
            
        src_ext = os.path.splitext(source_path)[1].lower().strip('.')
        
        # 1. 图像格式互转 (依赖 Pillow)
        image_formats = {'png', 'jpg', 'jpeg', 'webp', 'bmp', 'gif', 'tiff', 'ico'}
        if src_ext in image_formats and target_format in image_formats:
            from PIL import Image
            with Image.open(source_path) as img:
                # 兼容性处理，如果是存为jpg，不能有透明通道
                if target_format in ['jpg', 'jpeg']:
                    if img.mode in ('RGBA', 'LA', 'P'):
                        # 转换并填充白色背景
                        background = Image.new('RGB', img.size, (255, 255, 255))
                        if img.mode == 'RGBA':
                            background.paste(img, mask=img.split()[3])
                        else:
                            background.paste(img)
                        img = background
                img.save(dest_path)
            return f"✅ 图像格式转换成功：已保存为 '{dest_path}'"
            
        # 2. 表格与数据格式互转 (依赖 pandas/json)
        table_formats = {'csv', 'xlsx', 'json'}
        if src_ext in table_formats and target_format in table_formats:
            import pandas as pd
            import warnings
            warnings.filterwarnings('ignore', category=UserWarning) # 抑制 openpyxl 警告
            
            # 读取
            if src_ext == 'csv':
                df = pd.read_csv(source_path)
            elif src_ext == 'xlsx':
                df = pd.read_excel(source_path)
            else:
                df = pd.read_json(source_path, orient='records' if target_format != 'json' else None)
            
            # 写入
            if target_format == 'csv':
                df.to_csv(dest_path, index=False, encoding='utf-8-sig')
            elif target_format == 'xlsx':
                df.to_excel(dest_path, index=False)
            else:
                df.to_json(dest_path, orient='records', force_ascii=False, indent=2)
            return f"✅ 数据/表格转换成功：已保存为 '{dest_path}'"
            
        # 3. PDF/Word 转换为文本
        if src_ext == 'pdf' and target_format == 'txt':
            from pypdf import PdfReader
            with open(dest_path, "w", encoding="utf-8") as out:
                reader = PdfReader(source_path)
                for page in reader.pages:
                    text = page.extract_text()
                    if text:
                        out.write(text + "\n\n")
            return f"✅ 已成功将 PDF 提取为纯文本文件：'{dest_path}'"
            
        if src_ext == 'docx' and target_format == 'txt':
            import docx2txt
            text = docx2txt.process(source_path)
            with open(dest_path, "w", encoding="utf-8") as out:
                out.write(text)
            return f"✅ 已成功将 Word 提取为纯文本文件：'{dest_path}'"
            
        # 4. 高阶文档互转 PDF <-> Word
        if src_ext == 'pdf' and target_format == 'docx':
            try:
                from pdf2docx import Converter
                cv = Converter(source_path)
                cv.convert(dest_path, start=0, end=None)
                cv.close()
                return f"✅ 高级转换成功：PDF 已转为 Word '{dest_path}'"
            except ImportError:
                return "❌ 缺少 'pdf2docx' 库。如需将 PDF 转 Word，请让用户在命令行执行: pip install pdf2docx"
                
        if src_ext == 'docx' and target_format == 'pdf':
            try:
                from docx2pdf import convert
                convert(source_path, dest_path)
                return f"✅ 高级转换成功：Word 已转为 PDF '{dest_path}'"
            except (ImportError, Exception) as e:
                return f"❌ 将 Word 转为 PDF 失败或缺少 docx2pdf 依赖。请让用户执行: pip install docx2pdf。错误信息：{str(e)}"
                
        # 5. 音频/视频互转建议
        media_formats = {'mp4', 'mp3', 'wav', 'avi', 'mov', 'flac'}
        if src_ext in media_formats and target_format in media_formats:
            try:
                import ffmpeg
            except ImportError:
                 return "❌ 处理音视频转换需要 ffmpeg-python 库。请让用户执行：pip install ffmpeg-python"
            return "❌ 功能骨架存在，但需要安装配置 ffmpeg 执行实体才能进行音视频转换。"

        return f"❌ 尚未支持将后缀为 '{src_ext}' 的文件直接转换为 '{target_format}'，或该组合不支持。"
            
    except Exception as e:
        return f"❌ 转换过程中发生未捕获的错误：{type(e).__name__} - {str(e)}"
