#!/data/data/com.termux/files/usr/bin/bash
# 单独测试 Test 2 和 Test 7

set -e

# 测试配置
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_OUTPUT_DIR="$SCRIPT_DIR/test_output_2_7"
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
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

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

log_step() {
    echo -e "${CYAN}   → $1${NC}"
}

verify_file() {
    local file="$1"
    local expected_size="$2"
    local expected_sha256="$3"

    if [ ! -f "$file" ]; then
        log_error "文件不存在: $file"
        return 1
    fi

    log_step "检查文件大小..."
    actual_size=$(stat -c%s "$file" 2>/dev/null || stat -f%z "$file" 2>/dev/null)
    if [ "$actual_size" != "$expected_size" ]; then
        log_error "文件大小不匹配: 实际 $actual_size, 期望 $expected_size"
        return 1
    fi
    log_success "文件大小正确: $actual_size bytes"

    if [ -n "$expected_sha256" ]; then
        log_step "计算 SHA256 校验和..."
        actual_sha256=$(sha256sum "$file" | cut -d' ' -f1)
        if [ "$actual_sha256" != "$expected_sha256" ]; then
            log_error "SHA256 不匹配"
            return 1
        fi
        log_success "SHA256 校验正确"
    fi

    return 0
}

# 清理并创建测试目录
rm -rf "$TEST_OUTPUT_DIR"
mkdir -p "$TEST_OUTPUT_DIR"

echo "======================================================================"
echo -e "${BOLD}测试 2 和 7 单独测试${NC}"
echo "======================================================================"
echo ""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 2: 断点续传（优化版）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo "======================================================================"
echo -e "${BOLD}测试 2: 断点续传（优化版 - 30秒中断 + 低并发）${NC}"
echo "======================================================================"
echo ""

OUTPUT_FILE="$TEST_OUTPUT_DIR/resume.gguf"
PART_FILE="$OUTPUT_FILE.part"
CHECKPOINT_FILE="$OUTPUT_FILE.checkpoint"

log_step "第一次下载（将在30秒后中断，使用低并发确保慢速）..."
python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-cache \
    --concurrency 2 \
    -o "$OUTPUT_FILE" &

DOWNLOAD_PID=$!
echo "下载进程 PID: $DOWNLOAD_PID"
sleep 30
kill -INT $DOWNLOAD_PID 2>/dev/null || true
wait $DOWNLOAD_PID 2>/dev/null || true

sleep 2

log_step "检查断点文件..."
if [ -f "$CHECKPOINT_FILE" ]; then
    log_success "Checkpoint 文件存在"
    first_size=$(stat -c%s "$PART_FILE" 2>/dev/null || stat -f%z "$PART_FILE" 2>/dev/null || echo 0)
    log_info "部分文件大小: $first_size bytes"

    log_step "第二次下载（恢复）..."
    if python -m xet.cli.main download \
        "$TEST_REPO/$TEST_FILE" \
        --resume \
        --token "$TOKEN" \
        --proxy "$PROXY" \
        --no-cache \
        -o "$OUTPUT_FILE"; then

        log_step "验证最终文件..."
        if verify_file "$OUTPUT_FILE" "$EXPECTED_SIZE" "$EXPECTED_SHA256"; then
            log_success "${BOLD}测试 2 通过！${NC}"
            TEST2_RESULT="PASS"
        else
            log_error "${BOLD}测试 2 失败: 文件验证失败${NC}"
            TEST2_RESULT="FAIL"
        fi
    else
        log_error "${BOLD}测试 2 失败: 恢复下载失败${NC}"
        TEST2_RESULT="FAIL"
    fi
else
    log_warning "Checkpoint 文件不存在"
    log_error "${BOLD}测试 2 失败: 下载太快，未能在30秒内生成checkpoint${NC}"
    TEST2_RESULT="SKIP"
fi

echo ""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 7: 网络优化 + HF_ENDPOINT（优化版）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo "======================================================================"
echo -e "${BOLD}测试 7: 网络优化 + HF_ENDPOINT（优化版）${NC}"
echo "======================================================================"
echo ""

TEST7_RESULT="FAIL"

log_step "测试 7.1: 使用 --optimize-hosts（代理模式）..."
if python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --optimize-hosts \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-cache \
    -o "$TEST_OUTPUT_DIR/optimized.gguf" 2>&1 | tee "$TEST_OUTPUT_DIR/test7_optimize.log"; then

    log_step "检查日志..."
    if grep -qE "HOST 优选|优选完成|DoH" "$TEST_OUTPUT_DIR/test7_optimize.log"; then
        log_success "日志包含 HOST 优化信息"
    else
        log_warning "日志未显示 HOST 优化过程"
    fi

    if verify_file "$TEST_OUTPUT_DIR/optimized.gguf" "$EXPECTED_SIZE" "$EXPECTED_SHA256"; then
        log_success "代理 + IP 优选模式下载成功"
        rm -f "$TEST_OUTPUT_DIR/optimized.gguf"
        TEST7_1_PASS=true
    else
        log_error "文件验证失败"
        TEST7_1_PASS=false
    fi
else
    if grep -qE "Connection reset|Connection timed out|Failed to establish|Max retries exceeded" "$TEST_OUTPUT_DIR/test7_optimize.log"; then
        log_warning "网络连接失败（环境问题）"
        TEST7_1_PASS=skip
    else
        log_error "IP 优选模式下载失败"
        TEST7_1_PASS=false
    fi
fi

echo ""

log_step "测试 7.2: 使用 --hf-endpoint hf-mirror.com（直连模式）..."
if python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --hf-endpoint https://hf-mirror.com \
    --token "$TOKEN" \
    --no-cache \
    --mode direct \
    -o "$TEST_OUTPUT_DIR/mirror.gguf" 2>&1 | tee "$TEST_OUTPUT_DIR/test7_mirror.log"; then

    log_step "检查日志..."
    if grep -qE "hf-mirror|HF 端点|自定义 HF 端点" "$TEST_OUTPUT_DIR/test7_mirror.log"; then
        log_success "日志显示使用了 hf-mirror.com"
    fi

    if verify_file "$TEST_OUTPUT_DIR/mirror.gguf" "$EXPECTED_SIZE" "$EXPECTED_SHA256"; then
        log_success "hf-mirror.com 直连下载成功"
        TEST7_2_PASS=true
    else
        log_error "hf-mirror.com 下载文件验证失败"
        TEST7_2_PASS=false
    fi
else
    log_warning "hf-mirror.com 直连失败（可能网络问题）"
    TEST7_2_PASS=false
fi

# 判断测试 7 整体结果
if [ "$TEST7_1_PASS" = "true" ] || [ "$TEST7_2_PASS" = "true" ]; then
    log_success "${BOLD}测试 7 通过！（至少一种模式成功）${NC}"
    TEST7_RESULT="PASS"
elif [ "$TEST7_1_PASS" = "skip" ] && [ "$TEST7_2_PASS" = "false" ]; then
    log_warning "${BOLD}测试 7 部分通过（IP 优选跳过，hf-mirror 失败）${NC}"
    TEST7_RESULT="PARTIAL"
else
    log_error "${BOLD}测试 7 失败（两种模式均失败）${NC}"
    TEST7_RESULT="FAIL"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 最终报告
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "======================================================================"
echo -e "${BOLD}最终报告${NC}"
echo "======================================================================"
echo ""
echo -e "测试 2（断点续传）: ${TEST2_RESULT}"
echo -e "测试 7（网络优化）: ${TEST7_RESULT}"
echo ""

if [ "$TEST2_RESULT" = "PASS" ] && [ "$TEST7_RESULT" = "PASS" ]; then
    echo -e "${GREEN}${BOLD}✅ 所有测试通过！${NC}"
    exit 0
else
    echo -e "${YELLOW}${BOLD}⚠️  部分测试失败或跳过${NC}"
    exit 1
fi
