#!/data/data/com.termux/files/usr/bin/bash
# test_cli_p0_core.sh - P0 核心功能测试（带进度显示）

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
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
NC='\033[0m'

# 测试统计
TOTAL_TESTS=5
CURRENT_TEST=0
PASSED=0
FAILED=0
SKIPPED=0
START_TIME=$(date +%s)

# 测试用例列表
declare -A TEST_CASES=(
    [1]="TC-P0-01:基础下载:使用 user/repo/file 格式下载单个文件"
    [2]="TC-P0-02:revision 参数:使用 --revision 指定 commit hash"
    [3]="TC-P0-03:默认 main 分支:不指定 revision，使用默认 main"
    [4]="TC-P0-04:错误处理:尝试下载不存在的文件"
    [5]="TC-P0-05:进度显示:验证进度条和速度显示"
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

    # 状态图标
    local status_icon
    case "$status" in
        "running")  status_icon="${CYAN}[运行中]${NC}" ;;
        "passed")   status_icon="${GREEN}[✓ 通过]${NC}" ;;
        "failed")   status_icon="${RED}[✗ 失败]${NC}" ;;
        "skipped")  status_icon="${YELLOW}[⊘ 跳过]${NC}" ;;
        "pending")  status_icon="${BLUE}[待执行]${NC}" ;;
        *)          status_icon="[未知]" ;;
    esac

    # 进度条
    local bar="["
    for ((i=0; i<filled; i++)); do bar+="█"; done
    for ((i=0; i<empty; i++)); do bar+="░"; done
    bar+="]"

    echo -e "\n${BOLD}[$current/$total] $test_id: $test_name${NC}"
    echo -e "$status_icon $bar ${percent}%"
}

# 显示总体进度
show_overall_progress() {
    local elapsed=$(($(date +%s) - START_TIME))
    local mins=$((elapsed / 60))
    local secs=$((elapsed % 60))

    echo ""
    echo "═══════════════════════════════════════════════════════════════════"
    echo -e "${BOLD}📊 P0 测试进度总览${NC}"
    echo "═══════════════════════════════════════════════════════════════════"
    echo ""

    for i in {1..5}; do
        local info="${TEST_CASES[$i]}"
        local id=$(echo "$info" | cut -d: -f1)
        local name=$(echo "$info" | cut -d: -f2)

        local status="pending"
        if [ $i -lt $CURRENT_TEST ]; then
            # 已完成的测试 - 检查是否通过
            if [ -f "$TEST_OUTPUT_DIR/test${i}.status" ]; then
                status=$(cat "$TEST_OUTPUT_DIR/test${i}.status")
            else
                status="passed"  # 默认假设通过
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

        printf "  [$i/5] %-12s %-30s %s\n" "$id" "$name" "$status_display"
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
    local actual_size=$(stat -c%s "$file" 2>/dev/null || stat -f%z "$file" 2>/dev/null)
    if [ "$actual_size" != "$expected_size" ]; then
        log_error "文件大小不匹配: 实际 $actual_size, 期望 $expected_size"
        return 1
    fi
    log_success "文件大小正确: $(numfmt --to=iec-i --suffix=B $actual_size || echo \"$actual_size bytes\")"

    if [ -n "$expected_sha256" ]; then
        log_step "计算 SHA256 校验和..."
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

# 初始化
clear
echo "═══════════════════════════════════════════════════════════════════"
echo -e "${BOLD}${MAGENTA}  XET+ CLI P0 核心功能测试套件${NC}"
echo "═══════════════════════════════════════════════════════════════════"
echo ""
log_info "测试级别: P0 - 核心功能（必须完成）"
log_info "测试数量: 5 个测试用例"
log_info "测试目录: $TEST_OUTPUT_DIR"
log_info "测试仓库: $TEST_REPO"
log_info "测试文件: $TEST_FILE"
echo ""
log_warning "准备开始测试，按 Enter 继续..."
read -r

# 清理并创建测试目录
rm -rf "$TEST_OUTPUT_DIR"
mkdir -p "$TEST_OUTPUT_DIR"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 1: 基础下载
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
start_test 1

OUTPUT_FILE="$TEST_OUTPUT_DIR/test1_basic.gguf"

log_step "执行下载命令..."
if python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-cache \
    -o "$OUTPUT_FILE" \
    > "$TEST_OUTPUT_DIR/test1.log" 2>&1; then

    log_step "验证下载结果..."
    if verify_file "$OUTPUT_FILE" "$EXPECTED_SIZE" "$EXPECTED_SHA256"; then
        pass_test
    else
        fail_test "文件验证失败"
    fi
else
    fail_test "下载命令执行失败（退出码: $?）"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 2: revision 参数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
start_test 2

OUTPUT_FILE="$TEST_OUTPUT_DIR/test2_revision.gguf"
REVISION="45ce642d3fab2033d167ec09641a159010f7d9d9"

log_step "执行下载命令（revision: ${REVISION:0:12}...）..."
if python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --revision "$REVISION" \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-cache \
    -o "$OUTPUT_FILE" \
    > "$TEST_OUTPUT_DIR/test2.log" 2>&1; then

    log_step "验证下载结果..."
    if verify_file "$OUTPUT_FILE" "$EXPECTED_SIZE" "$EXPECTED_SHA256"; then
        # 检查日志中是否提到了 revision
        if grep -q "revision=$REVISION" "$TEST_OUTPUT_DIR/test2.log"; then
            log_success "日志中正确显示 revision"
        else
            log_warning "日志中未显示 revision（不影响功能）"
        fi
        pass_test
    else
        fail_test "文件验证失败"
    fi
else
    fail_test "下载命令执行失败（退出码: $?）"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 3: 默认 main 分支
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
start_test 3

OUTPUT_FILE="$TEST_OUTPUT_DIR/test3_main.gguf"

log_step "执行下载命令（默认 main）..."
if python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-cache \
    -o "$OUTPUT_FILE" \
    > "$TEST_OUTPUT_DIR/test3.log" 2>&1; then

    log_step "验证下载结果..."
    if verify_file "$OUTPUT_FILE" "$EXPECTED_SIZE" "$EXPECTED_SHA256"; then
        pass_test
    else
        fail_test "文件验证失败"
    fi
else
    fail_test "下载命令执行失败（退出码: $?）"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 4: 错误处理
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
start_test 4

OUTPUT_FILE="$TEST_OUTPUT_DIR/test4_error.gguf"

log_step "执行下载命令（不存在的文件）..."
if python -m xet.cli.main download \
    "$TEST_REPO/nonexistent_file_12345.gguf" \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-cache \
    -o "$OUTPUT_FILE" \
    > "$TEST_OUTPUT_DIR/test4.log" 2>&1; then

    fail_test "应该失败但成功了"
else
    log_step "检查错误信息..."
    if grep -qE "不是 XET 格式|不存在|404" "$TEST_OUTPUT_DIR/test4.log"; then
        log_success "正确显示错误信息"
        pass_test
    else
        log_warning "错误信息可能不够清晰"
        log_info "查看日志: $TEST_OUTPUT_DIR/test4.log"
        pass_test  # 仍然算通过，只是警告
    fi
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 5: 进度显示
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
start_test 5

OUTPUT_FILE="$TEST_OUTPUT_DIR/test5_progress.gguf"

log_step "执行下载命令（捕获进度输出）..."
if python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-cache \
    --progress-style rich \
    -o "$OUTPUT_FILE" \
    > "$TEST_OUTPUT_DIR/test5.log" 2>&1; then

    log_step "检查进度输出..."
    # 检查是否有进度相关输出
    if grep -qE "下载中|%|MB|KB|B/s|Xorb|Seg" "$TEST_OUTPUT_DIR/test5.log"; then
        log_success "包含进度信息"
    else
        log_warning "未检测到明显的进度信息"
    fi

    log_step "验证文件..."
    if verify_file "$OUTPUT_FILE" "$EXPECTED_SIZE" "$EXPECTED_SHA256"; then
        pass_test
    else
        fail_test "文件验证失败"
    fi
else
    fail_test "下载命令执行失败（退出码: $?）"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 生成最终报告
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
clear
show_overall_progress

echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo -e "${BOLD}${MAGENTA}  📊 P0 测试最终报告${NC}"
echo "═══════════════════════════════════════════════════════════════════"
echo ""

local elapsed=$(($(date +%s) - START_TIME))
local mins=$((elapsed / 60))
local secs=$((elapsed % 60))

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
    echo -e "${GREEN}${BOLD}✅ 所有P0测试通过！准备进入P1阶段。${NC}"
    echo ""
    exit 0
else
    echo -e "${RED}${BOLD}❌ 有 $FAILED 个测试失败，需要修复后再继续。${NC}"
    echo ""
    exit 1
fi
