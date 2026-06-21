# XET+ 测试指南

## 测试结构

```
xetplus/
├── tests/
│   ├── integration/
│   │   └── test_download_workflow.py   # 集成测试
│   └── unit/
│       └── test_xorb_cache.py          # 单元测试（已存在）
├── conftest.py                          # pytest 配置
└── pytest.ini                           # pytest 设置（可选）
```

## 运行测试

### 运行所有测试
```bash
cd xetplus
pytest tests/ -v
```

### 只运行单元测试
```bash
pytest tests/unit/ -v
```

### 只运行集成测试
```bash
pytest tests/integration/ -v
```

### 运行特定测试文件
```bash
pytest tests/integration/test_download_workflow.py -v
```

### 运行特定测试类
```bash
pytest tests/integration/test_download_workflow.py::TestDownloadWorkflow -v
```

### 运行特定测试方法
```bash
pytest tests/integration/test_download_workflow.py::TestDownloadWorkflow::test_cache_hit_workflow -v
```

## 测试标记

### 跳过需要真实环境的测试
```bash
# 只运行不需要真实环境的测试
pytest tests/ -v -m "not integration"
```

### 运行快速测试（跳过慢速测试）
```bash
pytest tests/ -v -m "not slow"
```

### 跳过需要网络的测试
```bash
pytest tests/ -v -m "not network"
```

## 当前测试状态

### 单元测试（可直接运行）
- ✅ `test_xorb_cache.py` - Xorb 磁盘缓存基本功能
  - 缓存命中/未命中
  - 大小验证
  - 统计信息

### 集成测试（部分需要真实环境）
- ✅ `test_cache_hit_workflow` - 缓存工作流（可运行）
- ✅ `test_cache_size_validation` - 缓存验证（可运行）
- ✅ `test_retry_coordinator_*` - RetryCoordinator 行为（可运行）
- ✅ `test_acc_*` - 自适应并发控制（可运行）
- ⚠️ `test_direct_mode_small_file` - 需要真实 CAS 服务器
- ⚠️ `test_xet_mode_large_file` - 需要真实 CAS 服务器
- ⚠️ `test_end_to_end_download_with_cache` - 需要真实环境
- ⚠️ `test_ip_optimization` - 需要真实网络环境

## 测试覆盖率

### 安装覆盖率工具
```bash
pip install pytest-cov
```

### 运行测试并生成覆盖率报告
```bash
# 终端输出
pytest tests/ --cov=xet --cov-report=term-missing -v

# HTML 报告
pytest tests/ --cov=xet --cov-report=html -v
# 然后打开 htmlcov/index.html
```

### 当前覆盖率估算
```
xet/pipeline/xorb_disk_cache.py        ~80%  # 有单元测试
xet/network/retry_coordinator.py       ~70%  # 有集成测试
xet/pipeline/adaptive_concurrency.py   ~60%  # 有集成测试
xet/cli/commands/download.py           ~30%  # 部分覆盖
xet/network/cas_client.py               ~20%  # 需要真实环境
其他模块                                ~10%  # 基本未覆盖
```

## 添加新测试

### 单元测试示例
```python
# tests/unit/test_my_module.py
import pytest
from xet.my_module import MyClass

class TestMyClass:
    def test_basic_functionality(self):
        obj = MyClass()
        result = obj.do_something()
        assert result == expected_value
```

### 集成测试示例
```python
# tests/integration/test_my_workflow.py
import pytest

@pytest.mark.integration
@pytest.mark.network
def test_my_workflow():
    # 需要真实环境的测试
    pass
```

### 使用 fixture
```python
# conftest.py
import pytest

@pytest.fixture
def temp_cache_dir(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    return cache_dir

# test_something.py
def test_with_cache(temp_cache_dir):
    # 使用 temp_cache_dir
    pass
```

## 模拟（Mocking）

### 模拟网络请求
```python
from unittest.mock import Mock, patch

@patch('xet.network.cas_client.CASClient.get_file_info')
def test_with_mock(mock_get_info):
    mock_get_info.return_value = {"size": 1024, "hash": "abc"}
    # 测试逻辑
```

### 模拟文件系统
```python
def test_with_temp_dir(tmp_path):
    # tmp_path 是 pytest 提供的临时目录
    test_file = tmp_path / "test.txt"
    test_file.write_text("test content")
    assert test_file.read_text() == "test content"
```

## 持续集成（CI）

### GitHub Actions 配置示例
```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.9'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov
      - name: Run tests
        run: |
          pytest tests/ -v --cov=xet --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v2
```

## 调试测试

### 进入调试模式
```bash
# 遇到失败时进入 pdb
pytest tests/ --pdb

# 遇到错误时进入 pdb
pytest tests/ --pdbcls=IPython.terminal.debugger:Pdb
```

### 查看详细输出
```bash
# 显示 print 输出
pytest tests/ -s

# 显示本地变量
pytest tests/ -l

# 详细回溯
pytest tests/ --tb=long
```

### 只运行失败的测试
```bash
# 第一次运行
pytest tests/ -v

# 只重跑失败的
pytest tests/ --lf

# 先跑失败的，再跑其他
pytest tests/ --ff
```

## 性能测试

### 使用 pytest-benchmark
```bash
pip install pytest-benchmark

# 运行性能测试
pytest tests/ --benchmark-only
```

### 示例
```python
def test_cache_performance(benchmark):
    from xet.pipeline.xorb_disk_cache import XorbDiskCache
    
    cache = XorbDiskCache(cache_dir="/tmp/bench_cache")
    test_data = b"x" * 1024 * 1024  # 1MB
    
    def put_operation():
        cache.put("test_hash", test_data)
    
    result = benchmark(put_operation)
    # benchmark 会自动运行多次并统计
```

## 测试最佳实践

1. **独立性** - 每个测试应该独立，不依赖其他测试
2. **确定性** - 测试结果应该可重复
3. **快速** - 单元测试应该快速运行（<1秒）
4. **清晰** - 测试名称应该描述测试内容
5. **隔离** - 使用 fixture 和 mock 隔离外部依赖

## 下一步

### 待添加的测试
1. [ ] DownloadScheduler 单元测试
2. [ ] FileReconstructor 单元测试
3. [ ] SegmentedReconstructor 单元测试
4. [ ] DomainAwareSession 单元测试
5. [ ] 端到端下载集成测试（需要 mock server）
6. [ ] 断点续传集成测试
7. [ ] IP 优选功能测试（需要真实网络）

### 测试目标
- 单元测试覆盖率 > 80%
- 核心模块 100% 覆盖
- 所有公共 API 都有测试
- 关键路径有集成测试

---

**最后更新**: 2026-06-20  
**维护者**: Claude & User
