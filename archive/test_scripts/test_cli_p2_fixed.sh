#!/data/data/com.termux/files/usr/bin/bash
# test_cli_p2_fixed.sh - P2 修复版测试脚本

set -e

# 测试配置
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_OUTPUT_DIR="$SCRIPT_DIR/test_output_cli_p2_fixed"
TOKEN="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"
PROXY="http://127.0.0.1:12334"
TEST_REPO="mykor/granite-embedding-97m-multilingual-r2-GGUF"
TEST_FILE="granite-embedding-97M-multilingual-r2-Q4_K_M.gguf"
EXPECTED_SIZE=105467232  # 100.58 MB
EXPECTED_SHA256="355f1f30ac3bdad09de420c5d78dd369e2a47d6f4ee3b5da342483f857965daf"

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# 检查代理
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}检查代理连接...${NC}"
if curl -x "$PROXY" --connect-timeout 3 -s https://www.google.com > /dev/null 2>&1; then
    echo -e "${GREEN}✅ 代理 $PROXY 可用${NC}"
else
    echo -e "${RED}❌ 代理 $PROXY 不可用！${NC}"
    echo -e "${YELLOW}请启动代理后重试：${NC}"
    echo -e "  export HTTPS_PROXY=$PROXY"
    exit 1
fi

# 清理并创建测试目录
rm -rf "$TEST_OUTPUT_DIR"
mkdir -p "$TEST_OUTPUT_DIR"

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}P2 修复版测试${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 1: 低内存模式
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo -e "${CYAN}[1/3] 测试：低内存模式 (--max-memory-mb 100)${NC}"
OUTPUT_FILE="$TEST_OUTPUT_DIR/low_memory.gguf"

if HTTPS_PROXY=$PROXY python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --max-memory-mb 100 \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-optimize-hosts \
    --no-cache \
    -o "$OUTPUT_FILE" \
    > "$TEST_OUTPUT_DIR/test1.log" 2>&1; then

    actual_size=$(stat -c%s "$OUTPUT_FILE" 2>/dev/null || stat -f%z "$OUTPUT_FILE")
    actual_sha256=$(sha256sum "$OUTPUT_FILE" | cut -d' ' -f1)

    if [ "$actual_size" = "$EXPECTED_SIZE" ] && [ "$actual_sha256" = "$EXPECTED_SHA256" ]; then
        echo -e "${GREEN}✅ 测试通过！文件大小和SHA256正确${NC}"
    else
        echo -e "${RED}❌ 测试失败！校验不匹配${NC}"
    fi
else
    echo -e "${RED}❌ 下载失败，查看日志: $TEST_OUTPUT_DIR/test1.log${NC}"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 2: 合理的分段下载 (修复版：20MB分片，文件100MB)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo -e "${CYAN}[2/3] 测试：分段下载 (--segment-size 20MB --parallel-segments 3)${NC}"
echo -e "${YELLOW}注：文件100MB，分成20MB段 = 约5个段，合理配置${NC}"
OUTPUT_FILE="$TEST_OUTPUT_DIR/segmented.gguf"

if HTTPS_PROXY=$PROXY python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --segment-size 20 \
    --parallel-segments 3 \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-optimize-hosts \
    --no-cache \
    -o "$OUTPUT_FILE" \
    > "$TEST_OUTPUT_DIR/test2.log" 2>&1; then

    actual_size=$(stat -c%s "$OUTPUT_FILE" 2>/dev/null || stat -f%z "$OUTPUT_FILE")
    actual_sha256=$(sha256sum "$OUTPUT_FILE" | cut -d' ' -f1)

    if [ "$actual_size" = "$EXPECTED_SIZE" ] && [ "$actual_sha256" = "$EXPECTED_SHA256" ]; then
        echo -e "${GREEN}✅ 测试通过！分段下载正确${NC}"
    else
        echo -e "${RED}❌ 测试失败！校验不匹配${NC}"
    fi
else
    echo -e "${RED}❌ 下载失败，查看日志: $TEST_OUTPUT_DIR/test2.log${NC}"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 测试 3: 并行写入
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo -e "${CYAN}[3/3] 测试：并行写入 (--parallel-write --buffer-mb 32)${NC}"
OUTPUT_FILE="$TEST_OUTPUT_DIR/parallel_write.gguf"

if HTTPS_PROXY=$PROXY python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --parallel-write \
    --buffer-mb 32 \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-optimize-hosts \
    --no-cache \
    -o "$OUTPUT_FILE" \
    > "$TEST_OUTPUT_DIR/test3.log" 2>&1; then

    actual_size=$(stat -c%s "$OUTPUT_FILE" 2>/dev/null || stat -f%z "$OUTPUT_FILE")
    actual_sha256=$(sha256sum "$OUTPUT_FILE" | cut -d' ' -f1)

    if [ "$actual_size" = "$EXPECTED_SIZE" ] && [ "$actual_sha256" = "$EXPECTED_SHA256" ]; then
        echo -e "${GREEN}✅ 测试通过！并行写入正确${NC}"
    else
        echo -e "${RED}❌ 测试失败！校验不匹配${NC}"
    fi
else
    echo -e "${RED}❌ 下载失败，查看日志: $TEST_OUTPUT_DIR/test3.log${NC}"
fi

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✅ P2修复版测试完成！${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "输出目录: $TEST_OUTPUT_DIR"
echo "日志文件: test1.log, test2.log, test3.log"
