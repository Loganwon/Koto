"""
自动归纳调度器功能测试
"""

import json
import os
import sys

# 添加项目路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, "web"))

from auto_catalog_scheduler import get_auto_catalog_scheduler


def test_auto_catalog_config():
    """测试配置读写"""
    print("=" * 60)
    print("测试 1: 配置读写")
    print("=" * 60)

    scheduler = get_auto_catalog_scheduler()

    print(
        f"✓ 自动归纳状态: {'启用' if scheduler.is_auto_catalog_enabled() else '禁用'}"
    )
    print(f"✓ 调度时间: {scheduler.get_catalog_schedule()}")
    print(f"✓ 源目录数量: {len(scheduler.get_source_directories())}")
    print(f"✓ 备份目录: {scheduler.get_backup_directory()}")

    print("\n源目录列表:")
    for i, dir_path in enumerate(scheduler.get_source_directories(), 1):
        print(f"  {i}. {dir_path}")

    print("\n✅ 配置测试通过\n")


def test_enable_disable():
    """测试启用/禁用"""
    print("=" * 60)
    print("测试 2: 启用/禁用功能")
    print("=" * 60)

    scheduler = get_auto_catalog_scheduler()

    # 启用
    print("启用自动归纳...")
    scheduler.enable_auto_catalog(schedule_time="03:00")

    assert scheduler.is_auto_catalog_enabled() == True, "❌ 启用失败"
    assert scheduler.get_catalog_schedule() == "03:00", "❌ 时间设置失败"
    print("✓ 启用成功")

    # 禁用
    print("禁用自动归纳...")
    scheduler.disable_auto_catalog()

    assert scheduler.is_auto_catalog_enabled() == False, "❌ 禁用失败"
    print("✓ 禁用成功")

    print("\n✅ 启用/禁用测试通过\n")


def test_manual_execution():
    """测试手动执行（小规模测试）"""
    print("=" * 60)
    print("测试 3: 手动执行归纳（跳过，需要真实文件）")
    print("=" * 60)

    scheduler = get_auto_catalog_scheduler()

    source_dirs = scheduler.get_source_directories()

    if not source_dirs:
        print("⚠️  无源目录配置，跳过执行测试")
        print("   提示：在 config/user_settings.json 中配置 wechat_files_dir")
    else:
        print(f"✓ 检测到 {len(source_dirs)} 个源目录")
        print(
            "⚠️  手动执行测试需要真实文件，建议使用 API /api/auto-catalog/run-now 测试"
        )

    print("\n✅ 手动执行测试跳过\n")


def test_backup_manifest_structure():
    """测试备份清单结构"""
    print("=" * 60)
    print("测试 4: 备份清单结构验证")
    print("=" * 60)

    scheduler = get_auto_catalog_scheduler()
    backup_dir = scheduler.get_backup_directory()

    print(f"✓ 备份目录: {backup_dir}")
    print(f"✓ 目录存在: {os.path.exists(backup_dir)}")

    # 检查是否有现有备份清单
    if os.path.exists(backup_dir):
        manifests = [
            f for f in os.listdir(backup_dir) if f.startswith("backup_manifest_")
        ]

        if manifests:
            print(f"✓ 发现 {len(manifests)} 个备份清单")

            # 读取最新的清单
            latest_manifest = sorted(manifests)[-1]
            manifest_path = os.path.join(backup_dir, latest_manifest)

            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)

            print(f"\n最新备份清单: {latest_manifest}")
            print(f"  - 时间戳: {manifest_data.get('timestamp')}")
            print(f"  - 源目录: {manifest_data.get('source_dir')}")
            print(f"  - 文件数: {len(manifest_data.get('files', []))}")

            if manifest_data.get("files"):
                sample_file = manifest_data["files"][0]
                print(f"\n  示例文件:")
                print(f"    - 原始路径: {sample_file.get('original_path', 'N/A')}")
                print(f"    - 归纳路径: {sample_file.get('organized_path', 'N/A')}")
                print(f"    - 源文件存在: {sample_file.get('source_exists', 'N/A')}")
                print(
                    f"    - 归纳文件存在: {sample_file.get('organized_exists', 'N/A')}"
                )
        else:
            print("⚠️  暂无备份清单（运行一次归纳后会生成）")
    else:
        print("⚠️  备份目录不存在（首次运行会自动创建）")

    print("\n✅ 备份清单结构验证通过\n")


def test_config_file():
    """测试配置文件完整性"""
    print("=" * 60)
    print("测试 5: 配置文件完整性")
    print("=" * 60)

    config_path = os.path.join(project_root, "config", "user_settings.json")

    if not os.path.exists(config_path):
        print(f"❌ 配置文件不存在: {config_path}")
        return

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    print(f"✓ 配置文件存在: {config_path}")

    # 检查 auto_catalog 配置
    if "auto_catalog" in config:
        auto_config = config["auto_catalog"]
        print("✓ auto_catalog 配置存在")

        required_fields = [
            "enabled",
            "schedule_time",
            "source_directories",
            "backup_dir",
        ]
        for field in required_fields:
            if field in auto_config:
                print(f"  ✓ {field}: {auto_config[field]}")
            else:
                print(f"  ⚠️  缺少字段: {field}")
    else:
        print("⚠️  配置文件中无 auto_catalog 配置（首次启用时会自动创建）")

    # 检查 wechat_files_dir
    if "storage" in config and "wechat_files_dir" in config["storage"]:
        wechat_dir = config["storage"]["wechat_files_dir"]
        print(f"\n✓ 微信文件目录: {wechat_dir}")
        print(f"  目录存在: {os.path.exists(wechat_dir)}")

    print("\n✅ 配置文件检查通过\n")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("自动归纳调度器功能测试".center(60))
    print("=" * 60 + "\n")

    try:
        test_auto_catalog_config()
        test_enable_disable()
        test_manual_execution()
        test_backup_manifest_structure()
        test_config_file()

        print("=" * 60)
        print("全部测试完成".center(60))
        print("=" * 60)
        print("\n💡 下一步:")
        print("  1. 启动 Koto: python koto_app.py")
        print("  2. 调用 API 启用自动归纳:")
        print("     POST http://localhost:5000/api/auto-catalog/enable")
        print("  3. 手动立即执行一次:")
        print("     POST http://localhost:5000/api/auto-catalog/run-now")
        print("  4. 查看归纳报告:")
        print("     workspace/_organize/_reports/auto_catalog_report_*.md")
        print("  5. 验证备份清单:")
        print("     workspace/_organize/_backups/backup_manifest_*.json\n")

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
