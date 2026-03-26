import os
import sys
import subprocess
import glob
import time

def print_header(title):
    print(f"\n{'='*10} {title} {'='*10}")

def check_git_status():
    print_header("1. 源文件修改状态 (Git Check)")
    try:
        result = subprocess.run(["git", "status", "-s"], capture_output=True, text=True)
        output = result.stdout.strip()
        if output:
            print("发现未提交的修改 (AI 修改成功的通常会在这里显示):")
            print(output)
        else:
            print("❌ 当前没有未提交的修改！(如果 AI 说改了代码，但这里是空，说明它没能实装)")
    except Exception as e:
        print(f"Git 状态检查失败: {e}")

def check_python_syntax():
    print_header("2. 后端语法健康检查 (Python Syntax)")
    print("正在检查 app/ 和 web/ 目录下的 Python 文件是否包含语法错误（避免热重载卡死）...")
    syntax_errors = 0
    directories_to_check = ["app", "web"]
    
    for directory in directories_to_check:
        if not os.path.exists(directory):
            continue
        for root, _, files in os.walk(directory):
            for file in files:
                if file.endswith(".py"):
                    filepath = os.path.join(root, file)
                    try:
                        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                            compile(f.read(), filepath, "exec")
                    except SyntaxError as e:
                        print(f"❌ 语法错误 [卡死元凶]: {filepath}")
                        try:
                            with open(filepath, "r", encoding="utf-8") as f:
                                lines = f.readlines()
                                print(f"    第 {e.lineno} 行: {lines[e.lineno-1].strip()}")
                        except:
                            pass
                        print(f"    错误信息: {e.msg}")
                        syntax_errors += 1
                        
    if syntax_errors == 0:
        print("✅ 后端所有 Python 文件语法检查通过。没有发现可能导致进程卡死的明显语法错误。")

def check_frontend_build():
    print_header("3. 前端静态资源构建检查 (Frontend Build)")
    univer_src_dir = os.path.join("web", "univer-editor")
    univer_dist_dir = os.path.join("web", "static", "univer-dist", "assets")
    
    # 查找最近修改的前端源文件
    src_files = []
    if os.path.exists(univer_src_dir):
        for ext in ["*.js", "*.css", "*.ts"]:
            src_files.extend(glob.glob(os.path.join(univer_src_dir, ext)))
            
    if not src_files:
        print("⚠️ 未找到前端源码文件")
        return
        
    latest_src_file = max(src_files, key=os.path.getmtime)
    src_time = os.path.getmtime(latest_src_file)
    print(f"最新修改的[源码]文件: {os.path.basename(latest_src_file)} ({time.ctime(src_time)})")
    
    # 查找最近生成的构建文件
    dist_files = []
    if os.path.exists(univer_dist_dir):
        for ext in ["*.js", "*.css"]:
            dist_files.extend(glob.glob(os.path.join(univer_dist_dir, ext)))
            
    if dist_files:
        latest_dist_file = max(dist_files, key=os.path.getmtime)
        dist_time = os.path.getmtime(latest_dist_file)
        print(f"最新生成的[产物]文件: {os.path.basename(latest_dist_file)} ({time.ctime(dist_time)})")
        
        if src_time > dist_time:
            print("❌ 警告: 你的源码比打包产物还要新！你需要重新运行前端打包 (esbuild)，否则页面加载的永远是旧代码。")
        else:
            print("✅ 前端打包产物是最新的。如果页面仍没变化，请**强制刷新浏览器 (Ctrl+F5)** 或禁用缓存。")
    else:
        print("❌ 未找到前端构建产物，请确认是否执行了前端打包脚本。")

def check_processes():
    print_header("4. 后端进程堆积检查 (Process Port/Zombie)")
    try:
        # Windows command to check python processes
        result = subprocess.run(["tasklist", "/fi", "imagename eq python.exe"], capture_output=True, text=True)
        py_count = result.stdout.lower().count("python.exe")
        print(f"当前运行的 python.exe 进程总数: {py_count}")
        if py_count > 3:
            print("⚠️ 警告: 发现大量 Python 进程！旧的服务可能没有正确关闭，这会导致端口占用(如 5000)或请求被旧进程拦截。")
            print("建议措施: 在终端执行 `taskkill /f /im python.exe` 杀掉所有残留进程，然后重启应用。")
        else:
            print("✅ 进程数量正常。")
    except Exception as e:
        print(f"进程检查失败: {e}")

if __name__ == "__main__":
    print("\n🚀 [Koto 全链路诊断系统启动] 🚀")
    print("=========================================")
    print("本脚本用于自动化排查 AI 修改代码未生效、链路卡死等问题。")
    
    check_git_status()
    check_python_syntax()
    check_frontend_build()
    check_processes()
    
    print("\n" + "="*41)
    print("诊断完成。请根据提示修复对应环节，或复制输出给 AI 寻求帮助。")
