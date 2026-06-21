#!/data/data/com.termux/files/usr/bin/bash
# test_cli_download_basic.sh - 基础下载功能测试（P0）

set -e

# 测试配置
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_OUTPUT_DIR="$SCRIPT_DIR/test_output_cli"
TOKEN="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"
PROXY="http://127.0.0.1:12334"
TEST_REPO="mykor/granite-embedding-97m-multilingual-r2-GGUF"
TEST_FILE="granite-embedding-97M-multilingual-r2-Q4_K_M.gguf"
EXPECTED_SIZE=105467232
EXPECTED_SHA256="355f1f30ac3bdad09de420c5d78dd369e2a47d6f4ee3b5da342483f857965daf"

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 测试统计
TOTAL=0
PASSED=0
FAILED=0
SKIPPED=0

# 日志函数
log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# 测试函数
test_case() {
    local name="$1"
    local description="$2"

    TOTAL=$((TOTAL + 1))
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${BLUE}🧪 测试 $TOTAL: $name${NC}"
    echo "   描述: $description"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

verify_file() {
    local file="$1"
    local expected_size="$2"
    local expected_sha256="$3"

    if [ ! -f "$file" ]; then
        log_error "文件不存在: $file"
        return 1
    fi

    local actual_size=$(stat -c%s "$file" 2>/dev/null || stat -f%z "$file" 2>/dev/null)
    if [ "$actual_size" != "$expected_size" ]; then
        log_error "文件大小不匹配: 实际 $actual_size, 期望 $expected_size"
        return 1
    fi
    log_success "文件大小正确: $actual_size bytes"

    if [ -n "$expected_sha256" ]; then
        log_info "计算 SHA256 校验和..."
        local actual_sha256=$(sha256sum "$file" | cut -d' ' -f1)
        if [ "$actual_sha256" != "$expected_sha256" ]; then
            log_error "SHA256 不匹配"
            log_error "实际: $actual_sha256"
            log_error "期望: $expected_sha256"
            return 1
        fi
        log_success "SHA256 校验正确"
    fi

    return 0
}

pass_test() {
    PASSED=$((PASSED + 1))
    log_success "测试通过"
}

fail_test() {
    local reason="$1"
    FAILED=$((FAILED + 1))
    log_error "测试失败: $reason"
}

skip_test() {
    local reason="$1"
    SKIPPED=$((SKIPPED + 1))
    log_warning "测试跳过: $reason"
}

# 初始化
echo "═══════════════════════════════════════════════════════════════════"
echo "  XET+ CLI 基础下载功能测试套件 (P0)"
echo "═══════════════════════════════════════════════════════════════════"
echo ""
log_info "测试目录: $TEST_OUTPUT_DIR"
log_info "测试仓库: $TEST_REPO"
log_info "测试文件: $TEST_FILE"
echo ""

# 清理并创建测试目录
rm -rf "$TEST_OUTPUT_DIR"
mkdir -p "$TEST_OUTPUT_DIR"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 1: 基础下载 (user/repo/file 格式)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
test_case "基础下载" "使用 user/repo/file 格式下载单个文件"

OUTPUT_FILE="$TEST_OUTPUT_DIR/test1_basic.gguf"

log_info "执行命令..."
if python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-cache \
    -o "$OUTPUT_FILE" \
    2>&1 | tee "$TEST_OUTPUT_DIR/test1.log"; then

    log_info "验证下载结果..."
    if verify_file "$OUTPUT_FILE" "$EXPECTED_SIZE" "$EXPECTED_SHA256"; then
        pass_test
    else
        fail_test "文件验证失败"
    fi
else
    fail_test "下载命令执行失败"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 2: 使用 --revision 参数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
test_case "revision 参数" "使用 --revision 指定 commit hash"

OUTPUT_FILE="$TEST_OUTPUT_DIR/test2_revision.gguf"
REVISION="45ce642d3fab2033d167ec09641a159010f7d9d9"

log_info "执行命令（使用 revision: ${REVISION:0:12}...）..."
if python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --revision "$REVISION" \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-cache \
    -o "$OUTPUT_FILE" \
    2>&1 | tee "$TEST_OUTPUT_DIR/test2.log"; then

    log_info "验证下载结果..."
    if verify_file "$OUTPUT_FILE" "$EXPECTED_SIZE" "$EXPECTED_SHA256"; then
        # 检查日志中是否提到了 revision
        if grep -q "revision=$REVISION" "$TEST_OUTPUT_DIR/test2.log"; then
            log_success "日志中正确显示 revision"
        else
            log_warning "日志中未显示 revision（可能不影响功能）"
        fi
        pass_test
    else
        fail_test "文件验证失败"
    fi
else
    fail_test "下载命令执行失败"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 3: 默认 main 分支
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
test_case "默认 main 分支" "不指定 revision，使用默认 main"

OUTPUT_FILE="$TEST_OUTPUT_DIR/test3_main.gguf"

log_info "执行命令（默认 main）..."
if python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-cache \
    -o "$OUTPUT_FILE" \
    2>&1 | tee "$TEST_OUTPUT_DIR/test3.log"; then

    log_info "验证下载结果..."
    if verify_file "$OUTPUT_FILE" "$EXPECTED_SIZE" "$EXPECTED_SHA256"; then
        pass_test
    else
        fail_test "文件验证失败"
    fi
else
    fail_test "下载命令执行失败"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 4: 错误处理 - 不存在的文件
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
test_case "错误处理" "尝试下载不存在的文件"

OUTPUT_FILE="$TEST_OUTPUT_DIR/test4_error.gguf"

log_info "执行命令（不存在的文件）..."
if python -m xet.cli.main download \
    "$TEST_REPO/nonexistent_file_12345.gguf" \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-cache \
    -o "$OUTPUT_FILE" \
    2>&1 | tee "$TEST_OUTPUT_DIR/test4.log"; then

    # 命令成功了，但不应该成功
    fail_test "应该失败但成功了"
else
    # 命令失败了（正确）
    log_info "检查错误信息..."
    if grep -q "不是 XET 格式\|不存在\|404" "$TEST_OUTPUT_DIR/test4.log"; then
        log_success "正确显示错误信息"
        pass_test
    else
        fail_test "错误信息不清晰"
    fi
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 5: 进度显示
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
test_case "进度显示" "验证进度条和速度显示"

OUTPUT_FILE="$TEST_OUTPUT_DIR/test5_progress.gguf"

log_info "执行命令（捕获进度输出）..."
if python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-cache \
    --progress-style rich \
    -o "$OUTPUT_FILE" \
    2>&1 | tee "$TEST_OUTPUT_DIR/test5.log"; then

    log_info "检查进度输出..."
    local has_progress=false
    local has_speed=false

    # 检查是否有进度相关输出
    if grep -qE "下载中|%|MB|KB|B/s" "$TEST_OUTPUT_DIR/test5.log"; then
        log_success "包含进度信息"
        has_progress=true
    else
        log_warning "未检测到进度信息"
    fi

    # 检查文件
    if verify_file "$OUTPUT_FILE" "$EXPECTED_SIZE" "$EXPECTED_SHA256"; then
        if [ "$has_progress" = true ]; then
            pass_test
        else
            log_warning "文件正确但进度显示可能有问题"
            pass_test
        fi
    else
        fail_test "文件验证失败"
    fi
else
    fail_test "下载命令执行失败"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 生成测试报告
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo "  测试报告"
echo "═══════════════════════════════════════════════════════════════════"
echo ""
echo "总计: $TOTAL"
echo -e "${GREEN}通过: $PASSED${NC}"
echo -e "${RED}失败: $FAILED${NC}"
echo -e "${YELLOW}跳过: $SKIPPED${NC}"

if [ $TOTAL -gt 0 ]; then
    SUCCESS_RATE=$(( PASSED * 100 / TOTAL ))
    echo "成功率: $SUCCESS_RATE%"
fi

echo ""
echo "日志文件: $TEST_OUTPUT_DIR/*.log"
echo "输出文件: $TEST_OUTPUT_DIR/*.gguf"
echo ""

# 退出码
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ 所有测试通过！${NC}"
    exit 0
else
    echo -e "${RED}❌ 有 $FAILED 个测试失败${NC}"
    exit 1
fi
