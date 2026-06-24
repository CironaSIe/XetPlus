"""optimize 命令单元测试。"""
import argparse
from unittest.mock import Mock, patch

import pytest

from xet.cli.commands.optimize import optimize_command, register_optimize_command

# 所有 download.py 的函数都从 xet.cli.commands.download 导入
_DL = "xet.cli.commands.download"
# XetAuth 从 xet.network.auth 导入（也是函数体内局部导入）
_AUTH = "xet.network.auth"


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_args():
    """创建模拟命令行参数。"""
    args = argparse.Namespace(
        refresh=False,
        refresh_doh=False,
        proxy=None,
        dns_servers=None,
        hosts=False,
        quiet=True,
        verbose=False,
        token=None,
        file_hash=None,
        cas_endpoint=None,
        repo=None,
        hf_endpoint=None,
    )
    return args


# ============================================================================
# 注册测试
# ============================================================================

def test_register_optimize_command():
    """测试命令注册。"""
    mock_subparsers = Mock()
    register_optimize_command(mock_subparsers)

    parser = mock_subparsers.add_parser.return_value
    call_args = [c[0][0] for c in parser.add_argument.call_args_list]
    assert "--refresh" in call_args
    assert "--proxy" in call_args
    assert "--repo" in call_args
    assert "--token" in call_args


# ============================================================================
# 基础优选（无 --repo）
# ============================================================================

def test_optimize_basic_no_results(mock_args):
    """测试基础优选无结果。"""
    with patch("xet.cli.commands.optimize.HostOptimizer") as cls:
        m = Mock()
        m.optimize.return_value = ({}, False, False)
        m.detailed_results = {}
        cls.return_value = m
        assert optimize_command(mock_args) == 1


def test_optimize_with_proxy(mock_args):
    """测试代理传给 HostOptimizer。"""
    mock_args.proxy = "http://127.0.0.1:10808"
    with patch("xet.cli.commands.optimize.HostOptimizer") as cls:
        m = Mock()
        m.optimize.return_value = ({"hf.co": {"ip": "1.2.3.4", "rtt": 0.1, "use_proxy": True}}, False, False)
        m.detailed_results = {}
        cls.return_value = m
        assert optimize_command(mock_args) == 0
        _, kw = cls.call_args
        assert kw["proxy"] == "http://127.0.0.1:10808"


def test_optimize_with_token_only_no_hash(mock_args):
    """有 token 但无 hash 时 token 直接传给 HostOptimizer。"""
    mock_args.token = "hf_test123"
    # 不设 file_hash，走 elif args.token and not _file_hash 分支
    with patch("xet.cli.commands.optimize.HostOptimizer") as cls:
        m = Mock()
        m.optimize.return_value = ({"cas.co": {"ip": "1.2.3.4", "rtt": 0.05, "use_proxy": False}}, False, False)
        m.detailed_results = {}
        cls.return_value = m
        assert optimize_command(mock_args) == 0
        _, kw = cls.call_args
        assert kw["access_token"] == "hf_test123"


def test_optimize_hosts_format(mock_args):
    """测试 hosts 格式输出。"""
    mock_args.hosts = True
    mappings = {
        "huggingface.co": {"ip": "52.222.136.89", "rtt": 0.1, "use_proxy": True},
    }
    with patch("xet.cli.commands.optimize.HostOptimizer") as cls:
        m = Mock()
        m.optimize.return_value = (mappings, False, False)
        m.detailed_results = {}
        cls.return_value = m
        with patch("builtins.print") as p:
            assert optimize_command(mock_args) == 0
            out = "\n".join(str(c) for c in p.call_args_list)
            assert "52.222.136.89" in out
            assert "# XET+ HOST" in out


def test_optimize_optimize_raises_exception(mock_args):
    """optimize() 方法抛异常时返回 1。"""
    with patch("xet.cli.commands.optimize.HostOptimizer") as cls:
        m = Mock()
        m.optimize.side_effect = RuntimeError("网络错误")
        m.detailed_results = {}
        cls.return_value = m
        assert optimize_command(mock_args) == 1


# ============================================================================
# --repo 模式：proxy 传递到 API session（核心 BUG 验证）
# ============================================================================

def test_repo_proxy_sets_session_proxies(mock_args):
    """验证 --repo + --proxy 时 session.proxies 被设置。"""
    mock_args.repo = "test/repo"
    mock_args.proxy = "http://127.0.0.1:7890"

    with patch("xet.cli.commands.optimize.ConfigManager") as cfg_cls:
        cfg = Mock()
        cfg.get_token.return_value = "tok"
        cfg.get_hf_endpoint.return_value = "https://huggingface.co"
        cfg_cls.return_value = cfg

        # 使用真实的 requests.Session 来验证 proxies 属性
        import types
        real_session = types.SimpleNamespace(proxies={})

        with patch("requests.Session", return_value=real_session):
            with patch(_DL + ".list_hf_files", return_value=[]):
                with patch("xet.cli.commands.optimize.HostOptimizer") as opt_cls:
                    opt = Mock()
                    opt.optimize.return_value = ({}, False, False)
                    opt.detailed_results = {}
                    opt_cls.return_value = opt

                    optimize_command(mock_args)

    assert real_session.proxies == {
        "http": "http://127.0.0.1:7890",
        "https": "http://127.0.0.1:7890",
    }


def test_repo_no_proxy_proxies_empty(mock_args):
    """无 --proxy 时 proxies 为空字典。"""
    mock_args.repo = "test/repo"
    mock_args.proxy = None

    import types
    real_session = types.SimpleNamespace(proxies={})

    with patch("xet.cli.commands.optimize.ConfigManager") as cfg_cls:
        cfg = Mock()
        cfg.get_token.return_value = "tok"
        cfg.get_hf_endpoint.return_value = "https://huggingface.co"
        cfg_cls.return_value = cfg

        with patch("requests.Session", return_value=real_session):
            with patch(_DL + ".list_hf_files", return_value=[]):
                with patch("xet.cli.commands.optimize.HostOptimizer") as opt_cls:
                    opt = Mock()
                    opt.optimize.return_value = ({}, False, False)
                    opt.detailed_results = {}
                    opt_cls.return_value = opt

                    optimize_command(mock_args)

    assert real_session.proxies == {}


# ============================================================================
# --repo 模式：detect_xet_file 返回 None（BUG 修复验证）
# ============================================================================

def test_repo_single_file_detect_none_no_crash(mock_args):
    """指定单文件时 detect_xet_file 返回 None 不崩溃。"""
    mock_args.repo = "user/repo/file.bin"
    mock_args.token = "hf_t"

    with patch("xet.cli.commands.optimize.ConfigManager") as cfg_cls:
        cfg = Mock()
        cfg.get_token.return_value = "hf_t"
        cfg.get_hf_endpoint.return_value = "https://huggingface.co"
        cfg_cls.return_value = cfg

        with patch(_DL + ".detect_xet_file", return_value=None):
            with patch("xet.cli.commands.optimize.HostOptimizer") as opt_cls:
                opt = Mock()
                opt.optimize.return_value = ({}, False, False)
                opt.detailed_results = {}
                opt_cls.return_value = opt

                result = optimize_command(mock_args)
                assert isinstance(result, int)


def test_repo_listed_file_detect_none_no_crash(mock_args):
    """列出文件后 detect_xet_file 返回 None 不崩溃。"""
    mock_args.repo = "user/repo"
    mock_args.token = "hf_t"

    with patch("xet.cli.commands.optimize.ConfigManager") as cfg_cls:
        cfg = Mock()
        cfg.get_token.return_value = "hf_t"
        cfg.get_hf_endpoint.return_value = "https://huggingface.co"
        cfg_cls.return_value = cfg

        with patch(_DL + ".list_hf_files", return_value=["file.bin"]):
            with patch(_DL + ".match_files", return_value=["file.bin"]):
                with patch(_DL + ".detect_xet_file", return_value=None):
                    with patch("xet.cli.commands.optimize.HostOptimizer") as opt_cls:
                        opt = Mock()
                        opt.optimize.return_value = ({}, False, False)
                        opt.detailed_results = {}
                        opt_cls.return_value = opt

                        result = optimize_command(mock_args)
                        assert isinstance(result, int)


# ============================================================================
# --repo 模式：正常获取 CAS token 流程
# ============================================================================

def test_repo_success_gets_cas_token(mock_args):
    """正常检测 xet 文件并获取 CAS token。"""
    mock_args.repo = "user/repo/model.gguf"
    mock_args.token = "hf_123"

    xet_info = {
        "xet_hash": "a" * 64,
        "auth_url": "https://hf.co/api/xet/auth",
        "size": 1000000000,
        "sha256": "abc",
    }

    with patch("xet.cli.commands.optimize.ConfigManager") as cfg_cls:
        cfg = Mock()
        cfg.get_token.return_value = "hf_123"
        cfg.get_hf_endpoint.return_value = "https://huggingface.co"
        cfg_cls.return_value = cfg

        with patch(_DL + ".detect_xet_file", return_value=xet_info):
            auth_mock = Mock()
            ti = Mock()
            ti.access_token = "cas_tok_xyz"
            ti.endpoint = "https://cas-server.xethub.hf.co"
            auth_mock.get_token.return_value = ti

            # XetAuth 是从 xet.network.auth 局部导入的
            with patch(_AUTH + ".XetAuth", return_value=auth_mock):
                with patch("xet.cli.commands.optimize.HostOptimizer") as opt_cls:
                    opt = Mock()
                    opt.optimize.return_value = (
                        {"hf.co": {"ip": "1.2.3.4", "rtt": 0.05, "use_proxy": True}},
                        False, False,
                    )
                    opt.detailed_results = {}
                    opt_cls.return_value = opt

                    assert optimize_command(mock_args) == 0

                    _, okw = opt_cls.call_args
                    assert okw["access_token"] == "cas_tok_xyz"
                    assert okw["file_hash"] == "a" * 64
                    assert okw["cas_endpoint"] == "https://cas-server.xethub.hf.co"


def test_repo_list_detects_first_xet_file(mock_args):
    """列出文件后遍历找到第一个 xet 文件（跳过非 xet 的）。"""
    mock_args.repo = "user/repo"
    mock_args.token = "hf_t"

    xet_info = {"xet_hash": "b" * 64, "auth_url": "https://hf.co/auth"}

    # match_files("*") 返回全部文件；detect 对 readme 返回 None，对 gguf 返回 info
    with patch("xet.cli.commands.optimize.ConfigManager") as cfg_cls:
        cfg = Mock()
        cfg.get_token.return_value = "hf_t"
        cfg.get_hf_endpoint.return_value = "https://huggingface.co"
        cfg_cls.return_value = cfg

        with patch(_DL + ".list_hf_files", return_value=["readme.txt", "model.gguf", "config.json"]):
            with patch(_DL + ".match_files", return_value=["readme.txt", "model.gguf", "config.json"]):
                # detect_xet_file: 第一次(readme)返回None, 第二次(gguf)返回info
                with patch(_DL + ".detect_xet_file", side_effect=[None, xet_info]) as df:
                    auth_mock = Mock()
                    ti = Mock()
                    ti.access_token = "ct"
                    ti.endpoint = None
                    auth_mock.get_token.return_value = ti

                    with patch(_AUTH + ".XetAuth", return_value=auth_mock):
                        with patch("xet.cli.commands.optimize.HostOptimizer") as opt_cls:
                            opt = Mock()
                            opt.optimize.return_value = ({}, False, False)
                            opt.detailed_results = {}
                            opt_cls.return_value = opt

                            optimize_command(mock_args)

                            # 应该被调用了2次（gguf优先排第一但返回None, readme第二也返回None...）
                            # 实际：sorted顺序 gguf(0) < readme(99)，所以先试 gguf
                            assert df.call_count == 2
                            # 第一次调用必须是 model.gguf（最高优先级）
                            ca_first = df.call_args_list[0][0]
                            assert ca_first[2] == "model.gguf"


def test_repo_priority_picks_gguf_first(mock_args):
    """优先选择 gguf 格式文件。"""
    mock_args.repo = "user/repo"
    mock_args.token = "hf_t"

    xet_info_gguf = {"xet_hash": "gg" * 32, "auth_url": "https://hf.co/auth"}
    xet_info_safetensors = {"xet_hash": "ss" * 32, "auth_url": "https://hf.co/auth"}

    # 文件列表：safetensors 排在前面但 gguf 优先级更高
    with patch("xet.cli.commands.optimize.ConfigManager") as cfg_cls:
        cfg = Mock()
        cfg.get_token.return_value = "hf_t"
        cfg.get_hf_endpoint.return_value = "https://huggingface.co"
        cfg_cls.return_value = cfg

        with patch(_DL + ".list_hf_files", return_value=["model.safetensors", "model.gguf"]):
            with patch(_DL + ".match_files", return_value=["model.safetensors", "model.gguf"]):
                # 两个都是 xet 文件，但因为排序 gguf 优先，应该先试 gguf
                with patch(_DL + ".detect_xet_file", side_effect=[xet_info_gguf]) as df:
                    auth_mock = Mock()
                    ti = Mock()
                    ti.access_token = "ct"
                    ti.endpoint = None
                    auth_mock.get_token.return_value = ti

                    with patch(_AUTH + ".XetAuth", return_value=auth_mock):
                        with patch("xet.cli.commands.optimize.HostOptimizer") as opt_cls:
                            opt = Mock()
                            opt.optimize.return_value = ({}, False, False)
                            opt.detailed_results = {}
                            opt_cls.return_value = opt

                            optimize_command(mock_args)

                            # 只调了一次就命中了（gguf 排第一优先）
                            assert df.call_count == 1
                            ca = df.call_args[0]
                            assert ca[2] == "model.gguf"


def test_repo_all_non_xet_falls_back_gracefully(mock_args):
    """所有文件都不是 xet 格式时优雅降级。"""
    mock_args.repo = "user/repo"
    mock_args.token = "hf_t"

    with patch("xet.cli.commands.optimize.ConfigManager") as cfg_cls:
        cfg = Mock()
        cfg.get_token.return_value = "hf_t"
        cfg.get_hf_endpoint.return_value = "https://huggingface.co"
        cfg_cls.return_value = cfg

        with patch(_DL + ".list_hf_files", return_value=["readme.md", ".gitattributes", "LICENSE"]):
            with patch(_DL + ".match_files", return_value=["readme.md", ".gitattributes", "LICENSE"]):
                # 所有文件都返回 None
                with patch(_DL + ".detect_xet_file", return_value=None) as df:
                    with patch("xet.cli.commands.optimize.HostOptimizer") as opt_cls:
                        opt = Mock()
                        opt.optimize.return_value = ({}, False, False)
                        opt.detailed_results = {}
                        opt_cls.return_value = opt

                        result = optimize_command(mock_args)

                        # 每个文件都尝试了一遍
                        assert df.call_count == 3
                        # 不崩溃，走基础测速
                        assert isinstance(result, int)


# ============================================================================
# --repo 模式：缺少 token
# ============================================================================

def test_repo_missing_token_exits(mock_args, capsys):
    """缺少 HF Token 时报错退出。"""
    mock_args.repo = "user/repo"

    mock_cfg = Mock()
    mock_cfg.get_token.return_value = None

    with patch("xet.cli.commands.optimize.ConfigManager", return_value=mock_cfg):
        assert optimize_command(mock_args) == 1
        assert "缺少 HF Token" in capsys.readouterr().err


# ============================================================================
# --repo 模式：异常处理
# ============================================================================

def test_repo_list_files_exception_graceful(mock_args, capsys):
    """列出文件异常时优雅降级。"""
    mock_args.repo = "user/repo"
    mock_args.token = "hf_t"

    with patch("xet.cli.commands.optimize.ConfigManager") as cfg_cls:
        cfg = Mock()
        cfg.get_token.return_value = "hf_t"
        cfg.get_hf_endpoint.return_value = "https://huggingface.co"
        cfg_cls.return_value = cfg

        with patch(_DL + ".list_hf_files", side_effect=Exception("网络错误")):
            with patch("xet.cli.commands.optimize.HostOptimizer") as opt_cls:
                opt = Mock()
                opt.optimize.return_value = ({}, False, False)
                opt.detailed_results = {}
                opt_cls.return_value = opt

                result = optimize_command(mock_args)
                assert isinstance(result, int)
                assert "自动获取 token 失败" in capsys.readouterr().err


# ============================================================================
# hf_endpoint 回退链
# ============================================================================

def test_hf_endpoint_explicit_overrides_config(mock_args):
    """显式 --hf-endpoint 覆盖配置。"""
    mock_args.repo = "user/repo/f.gguf"
    mock_args.token = "hf_t"
    mock_args.hf_endpoint = "https://custom.endpoint.com"

    with patch("xet.cli.commands.optimize.ConfigManager") as cfg_cls:
        cfg = Mock()
        cfg.get_token.return_value = "hf_t"
        cfg.get_hf_endpoint.return_value = "https://hf-mirror.com"
        cfg_cls.return_value = cfg

        with patch(_DL + ".detect_xet_file", return_value=None) as df:
            with patch("xet.cli.commands.optimize.HostOptimizer") as opt_cls:
                opt = Mock()
                opt.optimize.return_value = ({}, False, False)
                opt.detailed_results = {}
                opt_cls.return_value = opt

                optimize_command(mock_args)

                kws = df.call_args[1]
                assert kws["hf_endpoint"] == "https://custom.endpoint.com"


# ============================================================================
# dataset 类型仓库（需要3段路径才被判为 dataset）
# ============================================================================

def test_repo_three_part_dataset_type(mock_args):
    """三段路径被判为 dataset 类型且走 detect_xet_file 单文件路径。"""
    mock_args.repo = "datasets/user/dataset_name"
    mock_args.token = "hf_t"

    with patch("xet.cli.commands.optimize.ConfigManager") as cfg_cls:
        cfg = Mock()
        cfg.get_token.return_value = "hf_t"
        cfg.get_hf_endpoint.return_value = "https://huggingface.co"
        cfg_cls.return_value = cfg

        # 三段路径走 if filename: 分支，直接调 detect_xet_file（不经过 list_hf_files）
        with patch(_DL + ".detect_xet_file", return_value=None) as df:
            with patch("xet.cli.commands.optimize.HostOptimizer") as opt_cls:
                opt = Mock()
                opt.optimize.return_value = ({}, False, False)
                opt.detailed_results = {}
                opt_cls.return_value = opt

                optimize_command(mock_args)

                # 验证 repo_type 是 "dataset"，filename 被正确提取
                ca = df.call_args[0]
                assert ca[1] == "dataset"  # repo_type
                assert ca[2] == "dataset_name"  # filename


# ============================================================================
# 三级路径 user/repo/filename
# ============================================================================

def test_three_part_path_parsed_correctly(mock_args):
    """三级路径正确解析为 repo_id + filename。"""
    mock_args.repo = "org/repo/model.gguf"
    mock_args.token = "hf_t"

    xet_info = {"xet_hash": "c" * 64, "auth_url": "https://ex.com/auth"}

    with patch("xet.cli.commands.optimize.ConfigManager") as cfg_cls:
        cfg = Mock()
        cfg.get_token.return_value = "hf_t"
        cfg.get_hf_endpoint.return_value = "https://huggingface.co"
        cfg_cls.return_value = cfg

        with patch(_DL + ".detect_xet_file", return_value=xet_info) as df:
            auth_mock = Mock()
            ti = Mock()
            ti.access_token = "t"
            ti.endpoint = None
            auth_mock.get_token.return_value = ti

            with patch(_AUTH + ".XetAuth", return_value=auth_mock):
                with patch("xet.cli.commands.optimize.HostOptimizer") as opt_cls:
                    opt = Mock()
                    opt.optimize.return_value = ({}, False, False)
                    opt.detailed_results = {}
                    opt_cls.return_value = opt

                    optimize_command(mock_args)

                    ca = df.call_args[0]
                    assert ca[0] == "org/repo"
                    assert ca[2] == "model.gguf"


# ============================================================================
# 安静模式 / 详细模式
# ============================================================================

def test_quiet_mode_suppresses_output(mock_args, capsys):
    """安静模式抑制非必要输出。"""
    mock_args.quiet = True
    mock_args.hosts = False

    with patch("xet.cli.commands.optimize.HostOptimizer") as cls:
        m = Mock()
        m.optimize.return_value = ({"hf.co": {"ip": "1.2.3.4", "rtt": 0.1, "use_proxy": True}}, False, False)
        m.detailed_results = {}
        cls.return_value = m

        assert optimize_command(mock_args) == 0
        assert "HOST 优选结果" not in capsys.readouterr().out


def test_verbose_mode_calls_set_quiet(mock_args):
    """详细模式正确传递给优化器。"""
    mock_args.verbose = True

    with patch("xet.cli.commands.optimize.HostOptimizer") as cls:
        m = Mock()
        m.optimize.return_value = ({"hf.co": {"ip": "1.2.3.4", "rtt": 0.1, "use_proxy": True}}, False, False)
        m.detailed_results = {}
        cls.return_value = m

        with patch("builtins.print"):
            assert optimize_command(mock_args) == 0
            m.set_quiet.assert_called_once()
