#!/data/data/com.termux/files/usr/bin/bash
# test_cli_p2_advanced.sh - P2 高级功能测试

set -e

# 测试配置
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_OUTPUT_DIR="$SCRIPT_DIR/test_output_cli_p2"
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
MAGENTA='\033[0;35m'
BOLD='\033[1m'
NC='\033[0m'

# 测试统计
TOTAL_TESTS=6
CURRENT_TEST=0
PASSED=0
FAILED=0
SKIPPED=0
START_TIME=$(date +%s)

# 测试用例列表
declare -A TEST_CASES=(
    [1]="TC-P2-01:低内存模式:使用 --max-memory-mb 100 限制内存"
    [2]="TC-P2-02:分段下载:使用 --segment-size 256MB --parallel-segments 2"
    [3]="TC-P2-03:自定义 DNS:使用 --dns-servers 指定 DNS"
    [4]="TC-P2-04:重试控制:使用 --retry-max 3 控制重试次数"
    [5]="TC-P2-05:Checkpoint 间隔:使用 --checkpoint-interval 5 设置间隔"
    [6]="TC-P2-06:并行写入:使用 --parallel-write --buffer-mb 64"
)

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

# 进度显示
show_progress() {
    local current=$1
    local total=$2
    local test_id=$3
    local test_name=$4
    local status=$5

    local percent=$((current * 100 / total))
    local filled=$((current * 40 / total))
    local empty=$((40 - filled))

    local status_icon
    case "$status" in
        "running")  status_icon="${CYAN}[运行中]${NC}" ;;
        "passed")   status_icon="${GREEN}[✓ 通过]${NC}" ;;
        "failed")   status_icon="${RED}[✗ 失败]${NC}" ;;
        "skipped")  status_icon="${YELLOW}[⊘ 跳过]${NC}" ;;
        "pending")  status_icon="${BLUE}[待执行]${NC}" ;;
        *)          status_icon="[未知]" ;;
    esac

    local bar="["
    for ((i=0; i<filled; i++)); do bar+="█"; done
    for ((i=0; i<empty; i++)); do bar+="░"; done
    bar+="]"

    echo -e "\n${BOLD}[$current/$total] $test_id: $test_name${NC}"
    echo -e "$status_icon $bar ${percent}%"
}

# 显示总体进度
show_overall_progress() {
    elapsed=$(($(date +%s) - START_TIME))
    mins=$((elapsed / 60))
    secs=$((elapsed % 60))

    echo ""
    echo "═══════════════════════════════════════════════════════════════════"
    echo -e "${BOLD}📊 P2 测试进度总览${NC}"
    echo "═══════════════════════════════════════════════════════════════════"
    echo ""

    for i in {1..6}; do
        local info="${TEST_CASES[$i]}"
        local id=$(echo "$info" | cut -d: -f1)
        local name=$(echo "$info" | cut -d: -f2)

        local status="pending"
        if [ $i -lt $CURRENT_TEST ]; then
            if [ -f "$TEST_OUTPUT_DIR/test${i}.status" ]; then
                status=$(cat "$TEST_OUTPUT_DIR/test${i}.status")
            else
                status="passed"
            fi
        elif [ $i -eq $CURRENT_TEST ]; then
            status="running"
        fi

        local status_display
        case "$status" in
            "passed")   status_display="${GREEN}✅ 通过${NC}" ;;
            "failed")   status_display="${RED}❌ 失败${NC}" ;;
            "skipped")  status_display="${YELLOW}⊘ 跳过${NC}" ;;
            "running")  status_display="${CYAN}⏳ 运行中${NC}" ;;
            "pending")  status_display="${BLUE}⏸  待执行${NC}" ;;
        esac

        printf "  [$i/6] %-12s %-35s %s\n" "$id" "$name" "$status_display"
    done

    echo ""
    echo "─────────────────────────────────────────────────────────────────"
    printf "  ${BOLD}已完成: %d/%d${NC}  |  " "$((PASSED + FAILED + SKIPPED))" "$TOTAL_TESTS"
    printf "${GREEN}通过: %d${NC}  |  " "$PASSED"
    printf "${RED}失败: %d${NC}  |  " "$FAILED"
    printf "${YELLOW}跳过: %d${NC}\n" "$SKIPPED"
    printf "  ${BOLD}用时: %02d:%02d${NC}\n" "$mins" "$secs"
    echo "─────────────────────────────────────────────────────────────────"
    echo ""
}

# 测试函数
start_test() {
    local test_num=$1
    local test_info="${TEST_CASES[$test_num]}"
    local test_id=$(echo "$test_info" | cut -d: -f1)
    local test_name=$(echo "$test_info" | cut -d: -f2)
    local test_desc=$(echo "$test_info" | cut -d: -f3)

    CURRENT_TEST=$test_num

    clear
    show_overall_progress
    show_progress "$test_num" "$TOTAL_TESTS" "$test_id" "$test_name" "running"

    echo ""
    log_info "描述: $test_desc"
    echo ""
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

pass_test() {
    PASSED=$((PASSED + 1))
    echo "passed" > "$TEST_OUTPUT_DIR/test${CURRENT_TEST}.status"
    log_success "${BOLD}测试通过！${NC}"
    sleep 1
}

fail_test() {
    local reason="$1"
    FAILED=$((FAILED + 1))
    echo "failed" > "$TEST_OUTPUT_DIR/test${CURRENT_TEST}.status"
    log_error "${BOLD}测试失败: $reason${NC}"
    sleep 2
}

skip_test() {
    local reason="$1"
    SKIPPED=$((SKIPPED + 1))
    echo "skipped" > "$TEST_OUTPUT_DIR/test${CURRENT_TEST}.status"
    log_warning "${BOLD}测试跳过: $reason${NC}"
    sleep 1
}

# 初始化
clear
echo "═══════════════════════════════════════════════════════════════════"
echo -e "${BOLD}${MAGENTA}  XET+ CLI P2 高级功能测试套件${NC}"
echo "═══════════════════════════════════════════════════════════════════"
echo ""
log_info "测试级别: P2 - 高级功能"
log_info "测试数量: 6 个测试用例"
log_info "测试目录: $TEST_OUTPUT_DIR"
log_info "测试仓库: $TEST_REPO"
echo ""
log_info "自动开始测试..."
sleep 1

# 清理并创建测试目录
rm -rf "$TEST_OUTPUT_DIR"
mkdir -p "$TEST_OUTPUT_DIR"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 1: 低内存模式
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
start_test 1

OUTPUT_FILE="$TEST_OUTPUT_DIR/low_memory.gguf"

log_step "执行下载（--max-memory-mb 100）..."
if python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --max-memory-mb 100 \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-cache \
    -o "$OUTPUT_FILE" \
    > "$TEST_OUTPUT_DIR/test1.log" 2>&1; then

    log_step "检查日志..."
    if grep -qE "低内存|max.memory|memory.limit" "$TEST_OUTPUT_DIR/test1.log"; then
        log_success "日志显示使用低内存模式"
    else
        log_warning "日志未明确显示低内存模式（可能是默认行为）"
    fi

    if verify_file "$OUTPUT_FILE" "$EXPECTED_SIZE" "$EXPECTED_SHA256"; then
        pass_test
    else
        fail_test "文件验证失败"
    fi
else
    fail_test "下载命令执行失败"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 2: 分段下载
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
start_test 2

OUTPUT_FILE="$TEST_OUTPUT_DIR/segmented.gguf"

log_step "执行分段下载（--segment-size 256MB --parallel-segments 2）..."
if python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --segment-size 256 \
    --parallel-segments 2 \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-cache \
    -o "$OUTPUT_FILE" \
    > "$TEST_OUTPUT_DIR/test2.log" 2>&1; then

    log_step "检查日志..."
    if grep -qE "segment|分段|parallel" "$TEST_OUTPUT_DIR/test2.log"; then
        log_success "日志显示使用分段下载"
    else
        log_warning "日志未显示分段信息"
    fi

    if verify_file "$OUTPUT_FILE" "$EXPECTED_SIZE" "$EXPECTED_SHA256"; then
        pass_test
    else
        fail_test "文件验证失败"
    fi
else
    fail_test "分段下载失败"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 3: 自定义 DNS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
start_test 3

OUTPUT_FILE="$TEST_OUTPUT_DIR/custom_dns.gguf"

log_step "执行下载（--dns-servers 8.8.8.8,1.1.1.1）..."
if python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --dns-servers "8.8.8.8,1.1.1.1" \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-cache \
    -o "$OUTPUT_FILE" \
    > "$TEST_OUTPUT_DIR/test3.log" 2>&1; then

    log_step "检查日志..."
    if grep -qE "DNS|dns.servers|8\.8\.8\.8" "$TEST_OUTPUT_DIR/test3.log"; then
        log_success "日志显示使用自定义 DNS"
    else
        log_warning "日志未显示 DNS 信息"
    fi

    if verify_file "$OUTPUT_FILE" "$EXPECTED_SIZE" "$EXPECTED_SHA256"; then
        pass_test
    else
        fail_test "文件验证失败"
    fi
else
    fail_test "自定义 DNS 下载失败"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 4: 重试控制
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
start_test 4

OUTPUT_FILE="$TEST_OUTPUT_DIR/retry.gguf"

log_step "执行下载（--retry-max 3）..."
if python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --retry-max 3 \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-cache \
    -o "$OUTPUT_FILE" \
    > "$TEST_OUTPUT_DIR/test4.log" 2>&1; then

    log_step "检查日志..."
    if grep -qE "retry|重试|max.retry" "$TEST_OUTPUT_DIR/test4.log"; then
        log_success "日志显示重试配置"
    else
        log_warning "日志未显示重试信息（可能未触发重试）"
    fi

    if verify_file "$OUTPUT_FILE" "$EXPECTED_SIZE" "$EXPECTED_SHA256"; then
        pass_test
    else
        fail_test "文件验证失败"
    fi
else
    fail_test "重试控制测试失败"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 5: Checkpoint 间隔
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
start_test 5

OUTPUT_FILE="$TEST_OUTPUT_DIR/checkpoint.gguf"

log_step "执行下载（--checkpoint-interval 5）..."
if python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --checkpoint-interval 5 \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-cache \
    -o "$OUTPUT_FILE" \
    > "$TEST_OUTPUT_DIR/test5.log" 2>&1; then

    log_step "检查日志..."
    if grep -qE "checkpoint|检查点|interval" "$TEST_OUTPUT_DIR/test5.log"; then
        log_success "日志显示 checkpoint 信息"
    else
        log_warning "日志未显示 checkpoint 详情"
    fi

    if verify_file "$OUTPUT_FILE" "$EXPECTED_SIZE" "$EXPECTED_SHA256"; then
        pass_test
    else
        fail_test "文件验证失败"
    fi
else
    fail_test "Checkpoint 间隔测试失败"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 6: 并行写入
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
start_test 6

OUTPUT_FILE="$TEST_OUTPUT_DIR/parallel_write.gguf"

log_step "执行下载（--parallel-write --buffer-mb 64）..."
if python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --parallel-write \
    --buffer-mb 64 \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-cache \
    -o "$OUTPUT_FILE" \
    > "$TEST_OUTPUT_DIR/test6.log" 2>&1; then

    log_step "检查日志..."
    if grep -qE "parallel.write|并行写入|buffer" "$TEST_OUTPUT_DIR/test6.log"; then
        log_success "日志显示并行写入"
    else
        log_warning "日志未显示并行写入详情"
    fi

    if verify_file "$OUTPUT_FILE" "$EXPECTED_SIZE" "$EXPECTED_SHA256"; then
        pass_test
    else
        fail_test "文件验证失败"
    fi
else
    fail_test "并行写入测试失败"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 生成最终报告
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
clear
show_overall_progress

echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo -e "${BOLD}${MAGENTA}  📊 P2 测试最终报告${NC}"
echo "═══════════════════════════════════════════════════════════════════"
echo ""

elapsed=$(($(date +%s) - START_TIME))
mins=$((elapsed / 60))
secs=$((elapsed % 60))

echo -e "${BOLD}测试统计:${NC}"
echo "  总计: $TOTAL_TESTS"
echo -e "  ${GREEN}✅ 通过: $PASSED${NC}"
echo -e "  ${RED}❌ 失败: $FAILED${NC}"
echo -e "  ${YELLOW}⊘ 跳过: $SKIPPED${NC}"
echo ""

if [ $TOTAL_TESTS -gt 0 ]; then
    SUCCESS_RATE=$(( PASSED * 100 / TOTAL_TESTS ))
    echo -e "${BOLD}成功率: $SUCCESS_RATE%${NC}"
fi

echo ""
echo -e "${BOLD}用时: ${mins}分${secs}秒${NC}"
echo ""
echo -e "${BOLD}输出文件:${NC}"
echo "  日志: $TEST_OUTPUT_DIR/*.log"
echo "  文件: $TEST_OUTPUT_DIR/*.gguf"
echo ""

# 退出码
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}${BOLD}✅ 所有P2测试通过！${NC}"
    echo ""
    exit 0
else
    echo -e "${RED}${BOLD}❌ 有 $FAILED 个测试失败，需要修复后再继续。${NC}"
    echo ""
    exit 1
fi
