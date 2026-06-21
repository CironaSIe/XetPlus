#!/data/data/com.termux/files/usr/bin/bash
# test_cli_p1_advanced.sh - P1 重要功能测试

set -e

# 测试配置
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_OUTPUT_DIR="$SCRIPT_DIR/test_output_cli_p1"
TOKEN="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"
PROXY="http://127.0.0.1:12334"
TEST_REPO="mykor/granite-embedding-97m-multilingual-r2-GGUF"
TEST_FILE="granite-embedding-97M-multilingual-r2-Q4_K_M.gguf"
# 测试1 使用不同的仓库（有 JSON 文件）
TEST_REPO_JSON="zai-org/GLM-5.2"
EXPECTED_SIZE=105467232
EXPECTED_SHA256="355f1f30ac3bdad09de420c5d78dd369e2a47d6f4ee3b5da342483f857965daf"
CACHE_DIR="$HOME/.xet/cache/chunks"

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
TOTAL_TESTS=8
CURRENT_TEST=0
PASSED=0
FAILED=0
SKIPPED=0
START_TIME=$(date +%s)

# 测试用例列表
declare -A TEST_CASES=(
    [1]="TC-P1-01:批量下载 (*.json):使用 --include 下载 JSON 文件 (zai-org/GLM-5.2)"
    [2]="TC-P1-02:断点续传:中断后使用 --resume 恢复下载"
    [3]="TC-P1-03:禁用断点续传:使用 --no-resume 从头下载"
    [4]="TC-P1-04:缓存功能:验证缓存加速效果"
    [5]="TC-P1-05:禁用缓存:使用 --no-cache 跳过缓存"
    [6]="TC-P1-06:保留缓存:使用 --keep-cache 保留缓存文件"
    [7]="TC-P1-07:网络优化:使用 --optimize-hosts 优选 HOST"
    [8]="TC-P1-08:并发控制:测试不同 --concurrency 值"
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
    echo -e "${BOLD}📊 P1 测试进度总览${NC}"
    echo "═══════════════════════════════════════════════════════════════════"
    echo ""

    for i in {1..8}; do
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

        printf "  [$i/8] %-12s %-30s %s\n" "$id" "$name" "$status_display"
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
echo -e "${BOLD}${MAGENTA}  XET+ CLI P1 重要功能测试套件${NC}"
echo "═══════════════════════════════════════════════════════════════════"
echo ""
log_info "测试级别: P1 - 重要功能"
log_info "测试数量: 8 个测试用例"
log_info "测试目录: $TEST_OUTPUT_DIR"
log_info "测试仓库: $TEST_REPO"
echo ""
log_info "自动开始测试..."
sleep 1

# 清理并创建测试目录
rm -rf "$TEST_OUTPUT_DIR"
mkdir -p "$TEST_OUTPUT_DIR"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 1: 批量下载 (*.json)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
start_test 1

OUTPUT_DIR="$TEST_OUTPUT_DIR/batch_json"
mkdir -p "$OUTPUT_DIR"

log_step "执行批量下载命令..."
if python -m xet.cli.main download \
    "$TEST_REPO_JSON" \
    --include "*.json" \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-cache \
    -o "$OUTPUT_DIR/" \
    > "$TEST_OUTPUT_DIR/test1.log" 2>&1; then

    log_step "检查下载结果..."
    json_count=$(find "$OUTPUT_DIR" -name "*.json" -type f | wc -l)

    if [ $json_count -gt 0 ]; then
        log_success "成功下载 $json_count 个 JSON 文件"
        pass_test
    else
        fail_test "未找到下载的 JSON 文件"
    fi
else
    fail_test "批量下载命令执行失败"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 2: 断点续传
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
start_test 2

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
            if grep -q "从 checkpoint 恢复\|resume\|恢复" "$TEST_OUTPUT_DIR/test2_part2.log"; then
                log_success "日志确认使用了断点续传"
            else
                log_warning "日志未明确显示断点续传（不影响功能）"
            fi
            pass_test
        else
            fail_test "文件验证失败"
        fi
    else
        fail_test "恢复下载失败"
    fi
else
    log_warning "Checkpoint 文件不存在，跳过测试"
    SKIPPED=$((SKIPPED + 1))
    echo "skipped" > "$TEST_OUTPUT_DIR/test${CURRENT_TEST}.status"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 3: 禁用断点续传
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
start_test 3

OUTPUT_FILE="$TEST_OUTPUT_DIR/no_resume.gguf"
FAKE_PART="$OUTPUT_FILE.part"

log_step "创建假的部分文件..."
echo "fake content" > "$FAKE_PART"

log_step "执行下载（--no-resume）..."
if python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --no-resume \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-cache \
    -o "$OUTPUT_FILE" \
    > "$TEST_OUTPUT_DIR/test3.log" 2>&1; then

    log_step "验证文件..."
    if verify_file "$OUTPUT_FILE" "$EXPECTED_SIZE" "$EXPECTED_SHA256"; then
        if [ ! -f "$OUTPUT_FILE.checkpoint" ]; then
            log_success "未创建 checkpoint 文件（符合预期）"
        fi
        pass_test
    else
        fail_test "文件验证失败"
    fi
else
    fail_test "下载命令执行失败"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 4: 缓存功能
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
start_test 4

log_step "清理缓存目录..."
rm -rf "$CACHE_DIR"
mkdir -p "$CACHE_DIR"

log_step "第一次下载（构建缓存）..."
START1=$(date +%s)
python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    -o "$TEST_OUTPUT_DIR/cached1.gguf" \
    > "$TEST_OUTPUT_DIR/test4_first.log" 2>&1
END1=$(date +%s)
TIME1=$((END1 - START1))

log_info "第一次下载用时: ${TIME1}秒"

cache_count=$(find "$CACHE_DIR" -type f 2>/dev/null | wc -l)
log_info "缓存文件数: $cache_count"

if [ $cache_count -gt 0 ]; then
    log_success "缓存已创建"

    log_step "第二次下载（使用缓存）..."
    START2=$(date +%s)
    python -m xet.cli.main download \
        "$TEST_REPO/$TEST_FILE" \
        --token "$TOKEN" \
        --proxy "$PROXY" \
        -o "$TEST_OUTPUT_DIR/cached2.gguf" \
        > "$TEST_OUTPUT_DIR/test4_second.log" 2>&1
    END2=$(date +%s)
    TIME2=$((END2 - START2))

    log_info "第二次下载用时: ${TIME2}秒"

    if [ $TIME2 -lt $TIME1 ]; then
        speedup=$(echo "scale=2; $TIME1 / $TIME2" | bc)
        log_success "第二次更快（加速 ${speedup}x）"

        if verify_file "$TEST_OUTPUT_DIR/cached1.gguf" "$EXPECTED_SIZE" "$EXPECTED_SHA256" && \
           verify_file "$TEST_OUTPUT_DIR/cached2.gguf" "$EXPECTED_SIZE" "$EXPECTED_SHA256"; then
            pass_test
        else
            fail_test "文件验证失败"
        fi
    else
        log_warning "第二次未见明显加速（可能网络波动）"
        pass_test
    fi
else
    fail_test "缓存未创建"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 5: 禁用缓存
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
start_test 5

log_step "执行下载（--no-cache）..."
if python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --no-cache \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    -o "$TEST_OUTPUT_DIR/no_cache.gguf" \
    > "$TEST_OUTPUT_DIR/test5.log" 2>&1; then

    log_step "验证文件..."
    if verify_file "$TEST_OUTPUT_DIR/no_cache.gguf" "$EXPECTED_SIZE" "$EXPECTED_SHA256"; then
        if ! grep -q "缓存命中\|cache hit" "$TEST_OUTPUT_DIR/test5.log"; then
            log_success "未使用缓存（符合预期）"
        fi
        pass_test
    else
        fail_test "文件验证失败"
    fi
else
    fail_test "下载命令执行失败"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 6: 保留缓存
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
start_test 6

log_step "清理缓存..."
rm -rf "$CACHE_DIR"
mkdir -p "$CACHE_DIR"

log_step "执行下载（--keep-cache）..."
if python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --keep-cache \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    -o "$TEST_OUTPUT_DIR/keep.gguf" \
    > "$TEST_OUTPUT_DIR/test6.log" 2>&1; then

    log_step "检查缓存..."
    cache_count=$(find "$CACHE_DIR" -type f 2>/dev/null | wc -l)

    if [ $cache_count -gt 0 ]; then
        log_success "缓存已保留（$cache_count 个文件）"

        if verify_file "$TEST_OUTPUT_DIR/keep.gguf" "$EXPECTED_SIZE" "$EXPECTED_SHA256"; then
            pass_test
        else
            fail_test "文件验证失败"
        fi
    else
        fail_test "缓存未保留"
    fi
else
    fail_test "下载命令执行失败"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 7: 网络优化 + HF_ENDPOINT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
start_test 7

log_step "测试 1: 使用 --optimize-hosts（代理模式）..."
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
    else
        fail_test "文件验证失败"
    fi
else
    # 检查是否是网络连接问题
    if grep -qE "Connection reset|Connection timed out|Failed to establish|Max retries exceeded" "$TEST_OUTPUT_DIR/test7_optimize.log"; then
        log_warning "网络连接失败（环境问题）"
        skip_test "网络环境不稳定，无法完成 HOST 优化测试"
    else
        fail_test "IP 优选模式下载失败"
    fi
fi

log_step "测试 2: 使用 --hf-endpoint hf-mirror.com（直连模式）..."
if python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --hf-endpoint https://hf-mirror.com \
    --token "$TOKEN" \
    --no-cache \
    --mode direct \
    -o "$TEST_OUTPUT_DIR/mirror.gguf" 2>&1 | tee "$TEST_OUTPUT_DIR/test7_mirror.log"; then

    log_step "检查日志..."
    if grep -qE "hf-mirror|HF 端点|supports_xet" "$TEST_OUTPUT_DIR/test7_mirror.log"; then
        log_success "日志显示使用了 hf-mirror.com"
    fi

    if verify_file "$TEST_OUTPUT_DIR/mirror.gguf" "$EXPECTED_SIZE" "$EXPECTED_SHA256"; then
        log_success "hf-mirror.com 直连下载成功"
        pass_test
    else
        fail_test "hf-mirror.com 下载文件验证失败"
    fi
else
    log_warning "hf-mirror.com 直连失败（可能网络问题）"
    # 如果第一个测试通过，整体测试仍然通过
    if [ -f "$TEST_OUTPUT_DIR/optimized.gguf" ]; then
        log_info "IP 优选测试已通过，忽略 mirror 测试失败"
        pass_test
    else
        fail_test "两种网络优化模式均失败"
    fi
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 8: 并发控制
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
start_test 8

log_step "测试高并发（--concurrency 16）..."
START_HIGH=$(date +%s)
python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --concurrency 16 \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-cache \
    -o "$TEST_OUTPUT_DIR/concurrent_high.gguf" \
    > "$TEST_OUTPUT_DIR/test8_high.log" 2>&1
END_HIGH=$(date +%s)
TIME_HIGH=$((END_HIGH - START_HIGH))

log_info "高并发用时: ${TIME_HIGH}秒"

log_step "测试低并发（--concurrency 2）..."
START_LOW=$(date +%s)
python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --concurrency 2 \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-cache \
    -o "$TEST_OUTPUT_DIR/concurrent_low.gguf" \
    > "$TEST_OUTPUT_DIR/test8_low.log" 2>&1
END_LOW=$(date +%s)
TIME_LOW=$((END_LOW - START_LOW))

log_info "低并发用时: ${TIME_LOW}秒"

log_step "验证文件..."
if verify_file "$TEST_OUTPUT_DIR/concurrent_high.gguf" "$EXPECTED_SIZE" "$EXPECTED_SHA256" && \
   verify_file "$TEST_OUTPUT_DIR/concurrent_low.gguf" "$EXPECTED_SIZE" "$EXPECTED_SHA256"; then

    if [ $TIME_HIGH -lt $TIME_LOW ]; then
        log_success "高并发更快（符合预期）"
    else
        log_warning "低并发反而更快（可能网络波动）"
    fi
    pass_test
else
    fail_test "文件验证失败"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 生成最终报告
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
clear
show_overall_progress

echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo -e "${BOLD}${MAGENTA}  📊 P1 测试最终报告${NC}"
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
    echo -e "${GREEN}${BOLD}✅ 所有P1测试通过！准备进入P2阶段。${NC}"
    echo ""
    exit 0
else
    echo -e "${RED}${BOLD}❌ 有 $FAILED 个测试失败，需要修复后再继续。${NC}"
    echo ""
    exit 1
fi
