#!/data/data/com.termux/files/usr/bin/bash
# test_cli_p3_integration.sh - P3 集成测试（完整工作流）

set -e

# 测试配置
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_OUTPUT_DIR="$SCRIPT_DIR/test_output_cli_p3"
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
TOTAL_TESTS=4
PASSED=0
FAILED=0
START_TIME=$(date +%s)

log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

log_step() {
    echo -e "${CYAN}   → $1${NC}"
}

# 检查代理
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}检查测试环境...${NC}"
if curl -x "$PROXY" --connect-timeout 3 -s https://www.google.com > /dev/null 2>&1; then
    log_success "代理 $PROXY 可用"
else
    log_error "代理 $PROXY 不可用！请启动代理后重试"
    exit 1
fi

# 清理并创建测试目录
rm -rf "$TEST_OUTPUT_DIR"
mkdir -p "$TEST_OUTPUT_DIR"

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${MAGENTA}${BOLD}  XET+ CLI P3 集成测试套件${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 1: info 命令
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo -e "${CYAN}[1/4] TC-P3-01: info 命令${NC}"

log_step "执行 info 命令..."
if HTTPS_PROXY=$PROXY python -m xet.cli.main info \
    "$TEST_REPO/$TEST_FILE" \
    --token "$TOKEN" \
    > "$TEST_OUTPUT_DIR/test1.log" 2>&1; then

    log_step "验证输出..."
    if grep -qi "xet hash:" "$TEST_OUTPUT_DIR/test1.log" && \
       grep -q "大小:" "$TEST_OUTPUT_DIR/test1.log"; then
        log_success "测试通过！info 命令输出正确"
        PASSED=$((PASSED + 1))
    else
        log_error "测试失败！info 输出缺少必要字段"
        FAILED=$((FAILED + 1))
    fi
else
    log_error "测试失败！info 命令执行失败"
    FAILED=$((FAILED + 1))
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 2: config 命令
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo -e "${CYAN}[2/4] TC-P3-02: config 命令${NC}"

# 备份原配置（如果存在）
CONFIG_FILE="$HOME/.xetrc"
CONFIG_EXISTED=false
if [ -f "$CONFIG_FILE" ]; then
    CONFIG_EXISTED=true
    cp "$CONFIG_FILE" "$CONFIG_FILE.backup"
    log_step "已备份原配置"
fi

log_step "设置配置..."
python -m xet.cli.main config xet.token test_p3_token > "$TEST_OUTPUT_DIR/test2_set.log" 2>&1
python -m xet.cli.main config network.concurrency 8 >> "$TEST_OUTPUT_DIR/test2_set.log" 2>&1

log_step "读取配置..."
python -m xet.cli.main config --list > "$TEST_OUTPUT_DIR/test2_list.log" 2>&1

if grep -q "test_p3_token" "$TEST_OUTPUT_DIR/test2_list.log" && \
   grep -q "8" "$TEST_OUTPUT_DIR/test2_list.log"; then

    log_step "使用 --unset 删除测试配置..."
    python -m xet.cli.main config --unset xet.token > "$TEST_OUTPUT_DIR/test2_unset.log" 2>&1
    python -m xet.cli.main config --unset network.concurrency >> "$TEST_OUTPUT_DIR/test2_unset.log" 2>&1

    log_step "恢复原配置..."
    if [ "$CONFIG_EXISTED" = true ]; then
        # 恢复原配置
        mv "$CONFIG_FILE.backup" "$CONFIG_FILE"
    fi

    # 验证配置已清理
    python -m xet.cli.main config --list > "$TEST_OUTPUT_DIR/test2_final.log" 2>&1

    # 检查测试配置是否已删除
    if ! grep -q "test_p3_token" "$TEST_OUTPUT_DIR/test2_final.log"; then
        log_success "测试通过！config 命令正常工作（包括 --unset）"
        PASSED=$((PASSED + 1))
    else
        log_error "测试失败！配置未正确清理"
        log_step "实际配置内容："
        cat "$TEST_OUTPUT_DIR/test2_final.log" | grep -v "RuntimeWarning"
        FAILED=$((FAILED + 1))
    fi
else
    log_error "测试失败！配置未正确设置"
    FAILED=$((FAILED + 1))
    # 即使测试失败也要恢复配置
    if [ "$CONFIG_EXISTED" = true ] && [ -f "$CONFIG_FILE.backup" ]; then
        mv "$CONFIG_FILE.backup" "$CONFIG_FILE"
    fi
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 3: 完整下载工作流
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo -e "${CYAN}[3/4] TC-P3-03: 完整下载工作流${NC}"

OUTPUT_FILE="$TEST_OUTPUT_DIR/workflow.gguf"

log_step "执行完整下载流程..."
if HTTPS_PROXY=$PROXY python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-optimize-hosts \
    --concurrency 6 \
    -o "$OUTPUT_FILE" \
    > "$TEST_OUTPUT_DIR/test3.log" 2>&1; then

    actual_size=$(stat -c%s "$OUTPUT_FILE" 2>/dev/null || stat -f%z "$OUTPUT_FILE")
    actual_sha256=$(sha256sum "$OUTPUT_FILE" | cut -d' ' -f1)

    if [ "$actual_size" = "$EXPECTED_SIZE" ] && [ "$actual_sha256" = "$EXPECTED_SHA256" ]; then
        log_success "测试通过！完整工作流正常"
        PASSED=$((PASSED + 1))
    else
        log_error "测试失败！文件校验不通过"
        FAILED=$((FAILED + 1))
    fi
else
    log_error "测试失败！下载执行失败"
    FAILED=$((FAILED + 1))
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 4: 批量下载（所有 Q4 模型）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo -e "${CYAN}[4/4] TC-P3-04: 批量下载（所有 Q4 GGUF）${NC}"
echo -e "${YELLOW}注：从 $TEST_REPO 下载所有包含 Q4 的 .gguf 文件${NC}"

BATCH_DIR="$TEST_OUTPUT_DIR/batch_q4"
mkdir -p "$BATCH_DIR"

log_step "列出并下载所有 Q4 模型..."
if HTTPS_PROXY=$PROXY python -m xet.cli.main download \
    "$TEST_REPO" \
    --include "*Q4*.gguf" \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-optimize-hosts \
    --concurrency 4 \
    -o "$BATCH_DIR" \
    > "$TEST_OUTPUT_DIR/test4.log" 2>&1; then

    # 检查下载的文件数量
    file_count=$(find "$BATCH_DIR" -name "*.gguf" -type f | wc -l)

    if [ "$file_count" -gt 0 ]; then
        log_step "下载了 $file_count 个 Q4 模型文件"

        # 验证其中一个文件
        test_file=$(find "$BATCH_DIR" -name "*Q4_K_M.gguf" -type f | head -1)
        if [ -n "$test_file" ]; then
            actual_size=$(stat -c%s "$test_file" 2>/dev/null || stat -f%z "$test_file")
            actual_sha256=$(sha256sum "$test_file" | cut -d' ' -f1)

            if [ "$actual_size" = "$EXPECTED_SIZE" ] && [ "$actual_sha256" = "$EXPECTED_SHA256" ]; then
                log_success "测试通过！批量下载成功，文件校验通过"
                PASSED=$((PASSED + 1))
            else
                log_error "测试失败！文件校验不通过"
                FAILED=$((FAILED + 1))
            fi
        else
            log_success "测试通过！批量下载成功（$file_count 个文件）"
            PASSED=$((PASSED + 1))
        fi
    else
        log_error "测试失败！未找到 Q4 模型文件"
        FAILED=$((FAILED + 1))
    fi
else
    log_error "测试失败！批量下载执行失败"
    FAILED=$((FAILED + 1))
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 生成最终报告
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${MAGENTA}${BOLD}  📊 P3 测试最终报告${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

elapsed=$(($(date +%s) - START_TIME))
mins=$((elapsed / 60))
secs=$((elapsed % 60))

echo -e "${BOLD}测试统计:${NC}"
echo "  总计: $TOTAL_TESTS"
echo -e "  ${GREEN}✅ 通过: $PASSED${NC}"
echo -e "  ${RED}❌ 失败: $FAILED${NC}"
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
echo "  下载文件: $TEST_OUTPUT_DIR/*.gguf"
echo "  批量下载: $TEST_OUTPUT_DIR/batch_q4/*.gguf"
echo ""

# 退出码
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}${BOLD}✅ 所有P3测试通过！${NC}"
    echo ""
    exit 0
else
    echo -e "${RED}${BOLD}❌ 有 $FAILED 个测试失败${NC}"
    echo ""
    exit 1
fi
