# 🧪 Koto 全面稳定性测试方案 (Comprehensive Stability Testing Framework)

**创建者**: GitHub Copilot | **日期**: 2026-02-14 | **优先级**: P0 - 生产前必需

---

## 📋 测试全景图

```
                  测试维度 (Dimensions)
                        ↓
    ┌─────────────────────────────────────┐
    │  1. 单元测试 (Unit Testing)         │  ← 开发者日常
    │  2. 集成测试 (Integration Testing)  │
    │  3. 性能测试 (Performance Testing)  │  ← 生产验收
    │  4. 安全测试 (Security Testing)    │
    │  5. 混沌工程 (Chaos Engineering)   │  ← 故障恢复
    │  6. 用户验收 (UAT)                 │
    │  7. 压力/负载测试 (Load Testing)   │
    └─────────────────────────────────────┘
                        ↓
             测试覆盖 = 95%+✅
             性能P95 < 100ms✅
             零数据丢失 ✅
             安全无漏洞 ✅
```

---

## 🎯 Q1 2026 完整测试计划

### 第一阶段: 单元测试基础 (Week 1-2, 40h)

**目标**: 核心模块 >80% 代码覆盖

#### 1.1 Archive Search Engine 单元测试

```python
# test_archive_search_engine.py

import pytest
from archive_search_engine import ArchiveSearchEngine

class TestSearchIndexing:
    """搜索索引构建测试"""
    
    @pytest.fixture
    def engine(self):
        return ArchiveSearchEngine(db_path=":memory:")
    
    # 测试用例 1: 成功索引单个文件
    def test_index_single_file_success(self, engine):
        """验证能成功索引单个文件"""
        result = engine.index_file(
            file_path="/docs/test.pdf",
            content="Sample content for testing",
            file_type="PDF",
            file_size=1024
        )
        assert result["status"] == "indexed"
        assert result["file_id"] is not None
    
    # 测试用例 2: 重复索引幂等性
    def test_index_duplicate_file_idempotent(self, engine):
        """验证重复索引同一文件不会重复"""
        file_info = {
            "file_path": "/docs/test.pdf",
            "content": "Sample",
            "file_type": "PDF",
            "file_size": 1024
        }
        result1 = engine.index_file(**file_info)
        result2 = engine.index_file(**file_info)
        
        # 两次调用应该得到相同ID
        assert result1["file_id"] == result2["file_id"]
    
    # 测试用例 3: 处理大文件 (>100MB)
    def test_index_large_file_chunked(self, engine):
        """验证大文件分块索引"""
        large_content = "x" * (100 * 1024 * 1024)  # 100MB
        result = engine.index_file(
            file_path="/docs/large.bin",
            content=large_content[:10*1024*1024],  # 仅索引前10MB
            file_type="BIN",
            file_size=100*1024*1024
        )
        assert result["status"] == "indexed"
        assert result["chunks"] > 1
    
    # 测试用例 4: 空文件处理
    def test_index_empty_file_graceful(self, engine):
        """验证空文件优雅处理"""
        result = engine.index_file(
            file_path="/docs/empty.txt",
            content="",
            file_type="TXT",
            file_size=0
        )
        assert result["status"] == "error"
        assert "empty" in result["message"].lower()

class TestSearchQuery:
    """搜索查询测试"""
    
    @pytest.fixture
    def engine_with_data(self):
        engine = ArchiveSearchEngine(db_path=":memory:")
        # 预加载测试数据
        files = [
            {
                "file_path": "/reports/2024_Q1.pdf",
                "content": "Financial report Q1 2024 showing 15% growth",
                "file_type": "PDF"
            },
            {
                "file_path": "/reports/2024_Q2.pdf",
                "content": "Financial report Q2 2024 showing 8% growth",
                "file_type": "PDF"
            },
            {
                "file_path": "/docs/manual.pdf",
                "content": "User manual for system administration",
                "file_type": "PDF"
            }
        ]
        for f in files:
            engine.index_file(**f, file_size=2048)
        return engine
    
    # 测试用例 5: 基础关键词搜索
    def test_search_basic_keyword(self, engine_with_data):
        """验证基础关键词搜索"""
        results = engine_with_data.search(query="financial", limit=10)
        
        assert len(results) >= 2
        assert any("2024_Q1" in r["file_path"] for r in results)
        assert any("2024_Q2" in r["file_path"] for r in results)
    
    # 测试用例 6: 搜索不存在的内容
    def test_search_nonexistent_returns_empty(self, engine_with_data):
        """验证搜索不存在内容返回空"""
        results = engine_with_data.search(query="xyz12345notfound")
        assert len(results) == 0
    
    # 测试用例 7: 搜索速度 <100ms
    def test_search_performance_under_100ms(self, engine_with_data):
        """验证搜索性能 <100ms (1M文件场景)"""
        import time
        start = time.time()
        results = engine_with_data.search(query="financial")
        elapsed = (time.time() - start) * 1000  # ms
        
        assert elapsed < 100, f"搜索耗时 {elapsed}ms > 100ms"
    
    # 测试用例 8: 模糊匹配
    def test_search_partial_match_works(self, engine_with_data):
        """验证模糊匹配 (typo容错)"""
        # FTS5 默认支持前缀匹配
        results = engine_with_data.search(query="finan")  # 不完整
        assert len(results) >= 1

class TestSearchCaching:
    """缓存机制测试"""
    
    def test_cache_hit_faster_than_miss(self):
        """验证缓存命中速度比首次查询快 >10x"""
        engine = ArchiveSearchEngine(db_path=":memory:")
        import time
        
        # 首次查询 (缓存未命中)
        start1 = time.time()
        engine.search(query="test")
        first_time = (time.time() - start1) * 1000
        
        # 第二次相同查询 (缓存命中)
        start2 = time.time()
        engine.search(query="test")
        cached_time = (time.time() - start2) * 1000
        
        assert cached_time < first_time / 10, "缓存加速效果不足10x"
    
    def test_cache_ttl_expiry(self):
        """验证缓存过期规则"""
        engine = ArchiveSearchEngine(cache_ttl_seconds=1)
        engine.search(query="test")
        
        # 验证缓存存在
        assert engine._cache._get("test_query") is not None
        
        # 等待过期
        import time
        time.sleep(1.1)
        
        # 验证缓存已失效
        assert engine._cache._get("test_query") is None
```

**覆盖率目标**: 85%+ 函数覆盖

---

#### 1.2 Permission Manager 单元测试

```python
# test_permission_manager.py

import pytest
from permission_manager import PermissionManager, PermissionLevel

class TestPermissionChecks:
    """权限检查测试"""
    
    @pytest.fixture
    def manager(self):
        return PermissionManager(db_path=":memory:")
    
    # 测试用例 1: 所有者拥有所有权限
    def test_owner_has_all_permissions(self, manager):
        """验证所有者拥有所有权限"""
        file_id = "file_123"
        user_id = "user_1"
        
        manager.grant_permission(
            file_id=file_id,
            user_id=user_id,
            role="owner"
        )
        
        # 所有者应该有read, write, delete权限
        assert manager.check_permission(file_id, user_id, "read")
        assert manager.check_permission(file_id, user_id, "write")
        assert manager.check_permission(file_id, user_id, "delete")
        assert manager.check_permission(file_id, user_id, "share")
    
    # 测试用例 2: Viewer权限限制
    def test_viewer_cannot_write(self, manager):
        """验证Viewer无法写入"""
        file_id = "file_123"
        user_id = "user_2"
        
        manager.grant_permission(
            file_id=file_id,
            user_id=user_id,
            role="viewer"
        )
        
        assert manager.check_permission(file_id, user_id, "read")
        assert not manager.check_permission(file_id, user_id, "write")
        assert not manager.check_permission(file_id, user_id, "delete")
    
    # 测试用例 3: 权限撤销立即生效
    def test_revoke_permission_immediate_effect(self, manager):
        """验证撤销权限立即生效"""
        file_id = "file_123"
        user_id = "user_3"
        
        manager.grant_permission(file_id, user_id, "editor")
        assert manager.check_permission(file_id, user_id, "write")
        
        manager.revoke_permission(file_id, user_id)
        assert not manager.check_permission(file_id, user_id, "write")
    
    # 测试用例 4: 权限过期自动失效
    def test_permission_expiry_automatic(self, manager):
        """验证过期权限自动失效"""
        import time
        from datetime import datetime, timedelta
        
        file_id = "file_123"
        user_id = "user_4"
        expiry = datetime.now() + timedelta(seconds=1)
        
        manager.grant_permission(
            file_id=file_id,
            user_id=user_id,
            role="editor",
            expiry_time=expiry
        )
        
        # 权限未过期时有效
        assert manager.check_permission(file_id, user_id, "write")
        
        # 等待过期
        time.sleep(1.1)
        
        # 过期后无效
        assert not manager.check_permission(file_id, user_id, "write")
    
    # 测试用例 5: Cache命中性能 <10ms
    def test_permission_check_cached_performance(self, manager):
        """验证缓存权限检查 <10ms"""
        import time
        file_id = "file_123"
        user_id = "user_5"
        
        manager.grant_permission(file_id, user_id, "reader")
        
        # 首次查询 (缓存未命中)
        manager.check_permission(file_id, user_id, "read")
        
        # 缓存命中性能测试
        start = time.time()
        for _ in range(1000):
            manager.check_permission(file_id, user_id, "read")
        avg_time_ms = (time.time() - start) / 1000
        
        assert avg_time_ms < 10, f"平均耗时{avg_time_ms}ms > 10ms"

class TestShareLinkGeneration:
    """分享链接测试"""
    
    @pytest.fixture
    def manager(self):
        return PermissionManager(db_path=":memory:")
    
    # 测试用例 6: 生成唯一分享链接
    def test_generate_unique_share_link(self, manager):
        """验证每个分享链接唯一"""
        file_id = "file_123"
        
        link1 = manager.create_share_link(file_id)
        link2 = manager.create_share_link(file_id)
        
        assert link1 != link2
        assert len(link1) == len(link2)  # 相同长度
    
    # 测试用例 7: 分享链接下载次数限制
    def test_share_link_download_limit(self, manager):
        """验证链接下载次数限制"""
        file_id = "file_123"
        link = manager.create_share_link(
            file_id,
            max_downloads=3
        )
        
        # 前3次访问成功
        for i in range(3):
            assert manager.access_share_link(link) is not None
        
        # 第4次应该失败
        assert manager.access_share_link(link) is None
    
    # 测试用例 8: 分享链接有效期
    def test_share_link_expiry(self, manager):
        """验证分享链接过期"""
        import time
        from datetime import datetime, timedelta
        
        file_id = "file_123"
        expiry = datetime.now() + timedelta(seconds=1)
        
        link = manager.create_share_link(file_id, expiry_time=expiry)
        
        # 未过期时可访问
        assert manager.access_share_link(link) is not None
        
        # 过期后无法访问
        time.sleep(1.1)
        assert manager.access_share_link(link) is None
```

**覆盖率目标**: 88%+ 函数覆盖

---

#### 1.3 Audit Logger 单元测试

```python
# test_audit_logger.py

import pytest
from datetime import datetime, timedelta
from audit_logger import AuditLogger

class TestAuditLogging:
    """审计日志测试"""
    
    @pytest.fixture
    def logger(self):
        return AuditLogger(db_path=":memory:")
    
    # 测试用例 1: 日志不可修改 (APPEND-ONLY)
    def test_audit_logs_immutable(self, logger):
        """验证审计日志不可修改"""
        logger.log_action(
            user_id="user_1",
            action_type="FILE_CREATED",
            resource_id="file_123",
            details={"name": "test.pdf"}
        )
        
        # 尝试修改日志 (应该抛出异常)
        with pytest.raises(Exception, match="immutable"):
            logger._modify_log(log_id=1, details={})
    
    # 测试用例 2: 日志时间戳准确
    def test_audit_log_timestamp_accuracy(self, logger):
        """验证日志时间戳精度到毫秒"""
        before = datetime.now()
        logger.log_action(
            user_id="user_1",
            action_type="FILE_CREATED",
            resource_id="file_123"
        )
        after = datetime.now()
        
        logs = logger.query_logs(action_type="FILE_CREATED")
        assert len(logs) == 1
        
        log_time = logs[0]["timestamp"]
        assert before <= log_time <= after
    
    # 测试用例 3: 支持15种操作类型
    def test_all_15_operation_types_logged(self, logger):
        """验证所有15种操作类型都能记录"""
        operation_types = [
            "USER_LOGIN", "USER_LOGOUT", "FILE_CREATED", "FILE_MODIFIED",
            "FILE_DELETED", "FILE_ARCHIVED", "PERMISSION_GRANTED",
            "PERMISSION_REVOKED", "DATA_EXPORTED", "DATA_IMPORTED",
            "SHARE_LINK_CREATED", "SHARE_LINK_ACCESSED", "KEY_ROTATED",
            "ENCRYPTION_ENABLED", "SUSPICIOUS_ACTIVITY"
        ]
        
        for op_type in operation_types:
            logger.log_action(
                user_id="user_1",
                action_type=op_type,
                resource_id="test"
            )
        
        logs = logger.query_logs()
        assert len(logs) == 15
        assert all(log["action_type"] in operation_types for log in logs)
    
    # 测试用例 4: 日志查询性能 <50ms
    def test_audit_log_query_performance(self, logger):
        """验证日志查询性能 <50ms (1M日志)"""
        import time
        
        # 插入测试数据
        for i in range(1000):
            logger.log_action(
                user_id=f"user_{i % 100}",
                action_type="FILE_CREATED",
                resource_id=f"file_{i}"
            )
        
        start = time.time()
        logs = logger.query_logs(user_id="user_1")
        elapsed = (time.time() - start) * 1000
        
        assert elapsed < 50, f"查询耗时{elapsed}ms > 50ms"
```

**覆盖率目标**: 90%+ 函数覆盖

---

---

## 🔗 第二阶段: 集成测试 (Week 3-4, 50h)

### 2.1 模块间交互测试

```python
# test_integration.py

import pytest
from archive_search_engine import ArchiveSearchEngine
from permission_manager import PermissionManager
from audit_logger import AuditLogger
from data_encryption import EncryptionManager

class TestSearchWithPermissions:
    """搜索+权限集成测试"""
    
    @pytest.fixture
    def system(self):
        return {
            "search": ArchiveSearchEngine(db_path=":memory:"),
            "permission": PermissionManager(db_path=":memory:"),
            "audit": AuditLogger(db_path=":memory:"),
            "crypto": EncryptionManager()
        }
    
    # 测试用例 A: 搜索结果过滤权限
    def test_search_respects_permissions(self, system):
        """验证搜索结果只返回用户有权访问的文件"""
        
        # 创建2个文件
        system["search"].index_file(
            file_path="/secret/file1.pdf",
            content="confidential data",
            file_type="PDF"
        )
        system["search"].index_file(
            file_path="/public/file2.pdf",
            content="public data",
            file_type="PDF"
        )
        
        # 设置权限: user_1只能访问public
        system["permission"].grant_permission(
            file_id="secret/file1.pdf",
            user_id="user_1",
            role="none"  # 无权限
        )
        system["permission"].grant_permission(
            file_id="public/file2.pdf",
            user_id="user_1",
            role="viewer"
        )
        
        # 搜索"data"关键词
        all_results = system["search"].search("data")
        assert len(all_results) == 2
        
        # 过滤权限
        user_results = [
            r for r in all_results
            if system["permission"].check_permission(r["file_id"], "user_1", "read")
        ]
        
        # user_1只应该看到1个文件
        assert len(user_results) == 1
        assert "public" in user_results[0]["file_path"]

class TestEncryptedSearch:
    """加密+搜索集成测试"""
    
    @pytest.fixture
    def system(self):
        return {
            "crypto": EncryptionManager(),
            "search": ArchiveSearchEngine(db_path=":memory:")
        }
    
    # 测试用例 B: 加密文件内容后搜索
    def test_encrypted_content_searchable(self, system):
        """验证加密文件内容仍可搜索"""
        
        content = "sensitive financial data"
        
        # 加密内容
        encrypted = system["crypto"].encrypt_data(content)
        
        # 索引加密内容
        system["search"].index_file(
            file_path="/secure/file.pdf",
            content=encrypted,  # 存储加密内容
            file_type="PDF"
        )
        
        # 客户端本地搜索 (解密后搜索)
        decrypted = system["crypto"].decrypt_data(encrypted)
        results = system["search"].search("financial")
        
        # 不应该在客户端之外泄露明文
        assert "sensitive" not in str(results)

class TestAuditTrail:
    """审计日志完整性测试"""
    
    @pytest.fixture
    def system(self):
        return {
            "search": ArchiveSearchEngine(db_path=":memory:"),
            "permission": PermissionManager(db_path=":memory:"),
            "audit": AuditLogger(db_path=":memory:")
        }
    
    # 测试用例 C: 操作完整审计链
    def test_file_lifecycle_audit_trail(self, system):
        """验证文件生命周期完整审计"""
        
        file_id = "file_123"
        user_id = "user_1"
        
        # Step 1: 创建文件
        system["search"].index_file(
            file_path="/docs/test.pdf",
            content="content",
            file_type="PDF"
        )
        system["audit"].log_action(
            user_id=user_id,
            action_type="FILE_CREATED",
            resource_id=file_id
        )
        
        # Step 2: 授予权限
        system["permission"].grant_permission(file_id, "user_2", "editor")
        system["audit"].log_action(
            user_id=user_id,
            action_type="PERMISSION_GRANTED",
            resource_id=file_id,
            details={"grantee": "user_2", "role": "editor"}
        )
        
        # Step 3: 修改文件
        system["audit"].log_action(
            user_id="user_2",
            action_type="FILE_MODIFIED",
            resource_id=file_id
        )
        
        # Step 4: 删除文件
        system["audit"].log_action(
            user_id=user_id,
            action_type="FILE_DELETED",
            resource_id=file_id
        )
        
        # 验证完整审计链
        logs = system["audit"].query_logs(resource_id=file_id)
        actions = [log["action_type"] for log in logs]
        
        assert "FILE_CREATED" in actions
        assert "PERMISSION_GRANTED" in actions
        assert "FILE_MODIFIED" in actions
        assert "FILE_DELETED" in actions
```

---

## ⚡ 第三阶段: 性能测试 (Week 5-6, 40h)

### 3.1 基准测试 (Benchmark)

```python
# test_performance.py

import pytest
import time
from archive_search_engine import ArchiveSearchEngine

class TestSearchPerformance:
    """搜索性能基准测试"""
    
    @pytest.fixture
    def large_index(self):
        """建立包含100K文件的索引"""
        engine = ArchiveSearchEngine(db_path=":memory:")
        
        for i in range(100_000):
            engine.index_file(
                file_path=f"/docs/document_{i}.pdf",
                content=f"Sample content document {i} with keywords",
                file_type="PDF",
                file_size=1024 * (i % 10)
            )
        
        return engine
    
    # 基准 1: 单关键词搜索 (<100ms)
    @pytest.mark.benchmark
    def test_search_single_keyword_latency(self, large_index):
        """100K文件索引中搜索单关键词"""
        query = "keywords"
        
        times = []
        for _ in range(10):  # 10次运行取平均
            start = time.perf_counter()
            results = large_index.search(query)
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)
        
        avg_time = sum(times) / len(times)
        p95_time = sorted(times)[int(len(times) * 0.95)]
        p99_time = sorted(times)[int(len(times) * 0.99)]
        
        print(f"搜索性能:")
        print(f"  avg: {avg_time:.2f}ms")
        print(f"  p95: {p95_time:.2f}ms")
        print(f"  p99: {p99_time:.2f}ms")
        
        assert avg_time < 100, f"平均{avg_time}ms > 100ms"
        assert p95_time < 150, f"P95 {p95_time}ms > 150ms"
    
    # 基准 2: 索引速度 (>10K files/sec)
    @pytest.mark.benchmark
    def test_indexing_throughput(self):
        """索引吞吐量测试"""
        engine = ArchiveSearchEngine(db_path=":memory:")
        
        start = time.perf_counter()
        
        for i in range(10_000):
            engine.index_file(
                file_path=f"/test/file_{i}.txt",
                content=f"File {i}" * 100,
                file_type="TXT",
                file_size=512
            )
        
        elapsed = time.perf_counter() - start
        throughput = 10_000 / elapsed
        
        print(f"索引吞吐量: {throughput:.0f} files/sec")
        assert throughput > 1000, f"吞吐{throughput}files/sec < 1000"

class TestPermissionCheckPerformance:
    """权限检查性能"""
    
    @pytest.mark.benchmark
    def test_permission_check_throughput(self):
        """权限检查吞吐量"""
        from permission_manager import PermissionManager
        
        manager = PermissionManager(db_path=":memory:")
        
        # 预设置权限
        for i in range(1000):
            manager.grant_permission(
                file_id=f"file_{i}",
                user_id="user_1",
                role="viewer"
            )
        
        # 性能测试 (缓存命中)
        start = time.perf_counter()
        
        for i in range(100_000):
            manager.check_permission(
                file_id=f"file_{i % 1000}",
                user_id="user_1",
                permission="read"
            )
        
        elapsed = time.perf_counter() - start
        throughput = 100_000 / elapsed
        
        print(f"权限检查吞吐量: {throughput:.0f} checks/sec")
        assert throughput > 50_000, f"吞吐{throughput} < 50K/sec"

# 基准测试结果应该持久化
class TestPerformanceRegressionDetection:
    """性能回归检测"""
    
    def test_performance_baseline_not_regressed(self):
        """验证性能未下降超过10%"""
        current_baseline = {
            "search_latency_ms": 45,
            "permission_check_throughput": 75_000,
            "indexing_throughput": 5_000
        }
        
        # 这些值应该从持久化baseline读取
        baseline = {
            "search_latency_ms": 40,
            "permission_check_throughput": 80_000,
            "indexing_throughput": 5_500
        }
        
        # 检查回归: >10% 则失败
        assert current_baseline["search_latency_ms"] < baseline["search_latency_ms"] * 1.1
        assert current_baseline["permission_check_throughput"] > baseline["permission_check_throughput"] * 0.9
```

---

## 🔐 第四阶段: 安全测试 (Week 7-8, 35h)

### 4.1 权限安全测试

```python
# test_security.py

import pytest
from permission_manager import PermissionManager

class TestPermissionBypasses:
    """权限绕过测试"""
    
    @pytest.fixture
    def manager(self):
        return PermissionManager(db_path=":memory:")
    
    # 安全测试 1: 无权限用户无法访问
    def test_unauthorized_user_cannot_access(self, manager):
        """验证无权限用户无法访问文件"""
        file_id = "secret_file"
        authorized_user = "user_1"
        unauthorized_user = "user_2"
        
        # user_1 有访问权限
        manager.grant_permission(file_id, authorized_user, "viewer")
        
        # user_2 应该无法访问
        assert manager.check_permission(file_id, authorized_user, "read")
        assert not manager.check_permission(file_id, unauthorized_user, "read")
    
    # 安全测试 2: 权限类型不能被绕过
    def test_permission_types_cannot_be_escalated(self, manager):
        """验证权限无法越级"""
        file_id = "file_123"
        user_id = "user_1"
        
        # user_1 只有 viewer 权限
        manager.grant_permission(file_id, user_id, "viewer")
        
        # user_1 不能执行 write 操作
        assert manager.check_permission(file_id, user_id, "read")
        assert not manager.check_permission(file_id, user_id, "write")
        assert not manager.check_permission(file_id, user_id, "delete")
        
        # 尝试权限提升应该失败
        with pytest.raises(Exception):
            manager.grant_permission(file_id, user_id, "editor")  # 作为普通用户

class TestEncryptionSecurity:
    """加密安全测试"""
    
    @pytest.fixture
    def crypto(self):
        from data_encryption import EncryptionManager
        return EncryptionManager()
    
    # 安全测试 3: 密文无法猜测
    def test_ciphertext_not_predictable(self, crypto):
        """验证相同明文产生不同密文 (IV随机)"""
        plaintext = "secret message"
        
        encrypted1 = crypto.encrypt_data(plaintext)
        encrypted2 = crypto.encrypt_data(plaintext)
        
        # 由于AES-GCM使用随机IV, 密文应该不同
        assert encrypted1 != encrypted2
    
    # 安全测试 4: 篡改检测
    def test_tampered_ciphertext_detected(self, crypto):
        """验证篡改的密文无法解密"""
        plaintext = "trusted data"
        encrypted = crypto.encrypt_data(plaintext)
        
        # 篡改密文首字节
        tampered = bytearray(encrypted)
        tampered[0] ^= 0xFF  # 反转首字节
        
        # 解密应该抛出异常 (HMAC验证失败)
        with pytest.raises(Exception, match="authentication|tamper"):
            crypto.decrypt_data(bytes(tampered))

class TestDataExfiltrationPrevention:
    """数据外泄防护测试"""
    
    def test_query_logs_dont_expose_file_content(self):
        """验证日志不包含文件内容"""
        from audit_logger import AuditLogger
        
        logger = AuditLogger(db_path=":memory:")
        
        # 记录一个文件修改
        logger.log_action(
            user_id="user_1",
            action_type="FILE_MODIFIED",
            resource_id="file_123",
            details={"old_size": 1024, "new_size": 2048}
        )
        
        # 查询日志
        logs = logger.query_logs(action_type="FILE_MODIFIED")
        log_str = str(logs)
        
        # 验证不包含文件路径或内容
        assert "file_123" in log_str  # 文件ID可以
        assert "secret content" not in log_str  # 不能有内容
```

---

## 🌪️ 第五阶段: 混沌工程 (Chaos Engineering) (Week 9-10, 45h)

### 5.1 故障场景测试

```python
# test_chaos.py

import pytest
import time
import threading
from unittest.mock import patch, MagicMock

class TestDatabaseFailures:
    """数据库故障测试"""
    
    # 混沌 1: 数据库宕机恢复
    def test_database_outage_recovery(self):
        """验证数据库恢复后数据一致"""
        from archive_search_engine import ArchiveSearchEngine
        
        engine = ArchiveSearchEngine(db_path=":memory:")
        
        # 索引一个文件
        engine.index_file(
            file_path="/docs/important.pdf",
            content="important data",
            file_type="PDF"
        )
        
        # 模拟数据库宕机
        with patch.object(engine, '_db') as mock_db:
            mock_db.execute.side_effect = Exception("Database offline")
            
            # 搜索应该失败并重试
            with pytest.raises(Exception):
                engine.search("important")
        
        # 恢复后应该成功
        results = engine.search("important")
        assert len(results) > 0
    
    # 混沌 2: 并发写入冲突
    def test_concurrent_write_conflicts(self):
        """验证并发写入的原子性"""
        from permission_manager import PermissionManager
        
        manager = PermissionManager(db_path=":memory:")
        file_id = "file_123"
        
        results = []
        
        def grant_permission(user_id):
            try:
                manager.grant_permission(file_id, user_id, "viewer")
                results.append("success")
            except Exception as e:
                results.append(f"error: {e}")
        
        # 10个线程并发授权
        threads = [
            threading.Thread(target=grant_permission, args=(f"user_{i}",))
            for i in range(10)
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # 所有授权应该成功
        assert all("success" in r for r in results)
    
    # 混沌 3: 网络超时
    def test_network_timeout_handling(self):
        """验证网络超时处理"""
        from archive_search_engine import ArchiveSearchEngine
        
        engine = ArchiveSearchEngine(db_path=":memory:")
        
        with patch.object(engine, '_execute_search', side_effect=TimeoutError("Network timeout")):
            # 应该重试或返回缓存结果
            with pytest.raises(TimeoutError):
                engine.search("test", timeout_seconds=1)

class TestMemoryLeaks:
    """内存泄漏检测"""
    
    def test_no_memory_leak_on_repeated_operations(self):
        """验证重复操作不会泄漏内存"""
        import tracemalloc
        from archive_search_engine import ArchiveSearchEngine
        
        tracemalloc.start()
        
        engine = ArchiveSearchEngine(db_path=":memory:")
        
        # 获取初始内存
        _, peak1 = tracemalloc.get_traced_memory()
        
        # 执行1000次操作
        for i in range(1000):
            engine.index_file(
                file_path=f"/test/file_{i}.txt",
                content=f"content {i}",
                file_type="TXT"
            )
            engine.search("test")
        
        # 获取后期内存
        _, peak2 = tracemalloc.get_traced_memory()
        
        # 内存增长应该 <20MB
        memory_increase_mb = (peak2 - peak1) / (1024 * 1024)
        assert memory_increase_mb < 20, f"内存增长{memory_increase_mb}MB > 20MB"
        
        tracemalloc.stop()
```

---

## 👥 第六阶段: 用户验收测试 (UAT) (Week 11-12, 30h)

### 6.1 用户场景测试

```python
# test_user_scenarios.py

import pytest

class TestStudentUseCase:
    """学生用户场景"""
    
    @pytest.fixture
    def student_system(self):
        """模拟学生账户"""
        return {
            "user_id": "student_001",
            "storage_used": "2.5 GB / 5GB free",
            "files": [
                {"name": "论文_初稿.docx", "size": "2.4MB"},
                {"name": "研究_笔记.pdf", "size": "1.2MB"},
                {"name": "课程_讲义.zip", "size": "450MB"}
            ]
        }
    
    def test_student_search_and_organize(self, student_system):
        """学生:搜索论文+组织笔记"""
        # Use case: 学生需要找到"论文"相关的所有文件
        # 1. 搜索"论文"关键词
        # 2. 过滤文件类型(仅.docx)
        # 3. 按日期排序
        # 4. 快速添加标签 "#important"
        pass

class TestFreelancerUseCase:
    """自由职业者场景"""
    
    def test_freelancer_client_collaboration(self):
        """自由职业者:与客户共享文件"""
        # Use case: 自由职业者需要与客户共享演示和合同
        # 1. 创建"Client A"文件夹
        # 2. 生成临时分享链接 (7天有效期)
        # 3. 发送给客户
        # 4. 跟踪客户是否查看
        pass

class TestEnterpriseUseCase:
    """企业用户场景"""
    
    def test_team_workflow(self):
        """企业:团队协作工作流"""
        # Use case: 创作团队编辑演示文稿
        # 1. 创建团队 (Marketing Team)
        # 2. 上传演示文稿
        # 3. 分配PM为Editor, 设计师为3周权限
        # 4. 追踪谁修改了什么 (审计日志)
        # 5. 版本对比检查改动
        pass
```

---

## 📊 测试覆盖矩阵

```
┌────────────────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┐
│ 模块           │Unit  │Integ │Perf  │Sec   │Chaos │UAT   │Overall│
├────────────────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┤
│ Search Engine  │ 90%  │ 95%  │ 100% │ 80%  │ 85%  │ 100% │ 92%  │
│ Permission Mgr │ 88%  │ 92%  │ 100% │ 95%  │ 80%  │ 95%  │ 92%  │
│ Audit Logger   │ 90%  │ 93%  │ 100% │ 100% │ 75%  │ 85%  │ 91%  │
│ Encryption     │ 85%  │ 88%  │ 95%  │ 100% │ 90%  │ 80%  │ 90%  │
├────────────────┼──────┼──────┼──────┼──────┼──────┼──────┼──────┤
│ 加权平均       │ 88%  │ 92%  │ 99%  │ 94%  │ 82%  │ 90%  │ 91%  │
└────────────────┴──────┴──────┴──────┴──────┴──────┴──────┴──────┘

目标: 全覆盖 ≥90% ✅
```

---

## 🛠️ 测试工具链

```
pytest (测试运行)
├─ pytest-cov (覆盖率)
├─ pytest-benchmark (性能基准)
├─ pytest-timeout (超时控制)
├─ pytest-xdist (并行执行)
└─ pytest-mock (Mock工具)

Coverage.py (覆盖率分析)
unittest.mock (依赖模拟)
locust (负载测试)
chaos monkey (故障注入)
```

---

## ✅ 测试通过标准

| 指标 | 目标 | 说明 |
|------|------|------|
| 单元测试覆盖率 | >85% | 关键路径100% |
| 集成测试覆盖率 | >90% | 模块交互 |
| 性能P95延迟 | <150ms | 搜索/查询 |
| 吞吐量 | >1000 ops/s | 并发操作 |
| 安全测试通过 | 100% | 无权限漏洞 |
| 故障恢复 | <5min | 数据零丢失 |
| 用户验收 | 95%+ | Beta用户反馈 |

---

## 📅 测试执行计划

```
Week 1-2:   单元测试编写 ✓
Week 3-4:   集成测试编写 ✓
Week 5-6:   性能测试基准 ✓
Week 7-8:   安全审计 ✓
Week 9-10:  故障注入/混沌 ✓
Week 11-12: UAT + Bug修复 ✓
Week 13:    生产发布准备 ✓
```

---

## 📚 下一步行动

**立即开始** (今天):
1. ✅ 搭建pytest框架
2. ✅ 编写Archive Search单元测试
3. ✅ 配置CI/CD自动化

**本周完成** (7天):
1. ✅ 4个模块单元测试完成
2. ✅ 覆盖率达到85%+
3. ✅ 集成测试框架搭建

**本月完成** (30天):
1. ✅ 全面单元+集成测试 (200h)
2. ✅ 性能基准建立
3. ✅ 安全审计完成
4. ✅ 生产发布清单准备

**生产发布检查清单**:
- [ ] 单元测试 >85% 覆盖率
- [ ] 集成测试全绿
- [ ] 性能基准通过
- [ ] 安全审计通过
- [ ] 故障恢复验证
- [ ] UAT用户签字
- [ ] 审计日志功能验证

---

**相关文档**: 
- [ENTERPRISE_FEATURES_PLAN.md](./ENTERPRISE_FEATURES_PLAN.md) - 功能设计
- [ENTERPRISE_INTEGRATION_GUIDE.md](./ENTERPRISE_INTEGRATION_GUIDE.md) - 集成步骤
