#!/data/data/com.termux/files/usr/bin/bash
# 测试 --hf-endpoint 参数功能

set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "======================================================================="
echo "测试 --hf-endpoint 参数功能"
echo "======================================================================="
echo ""

TEST_REPO="mykor/granite-embedding-97m-multilingual-r2-GGUF"
TEST_FILE="granite-embedding-97M-multilingual-r2-Q4_K_M.gguf"
TEST_OUTPUT="/tmp/test_hf_endpoint.gguf"
TOKEN="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"
PROXY="http://127.0.0.1:12334"

# 清理
rm -f "$TEST_OUTPUT" "$TEST_OUTPUT.part" "$TEST_OUTPUT.checkpoint"

echo "测试 1: 使用 hf-mirror.com 直连（无代理）"
echo "-------------------------------------------------------------------"
python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --hf-endpoint https://hf-mirror.com \
    --token "$TOKEN" \
    --no-cache \
    --mode direct \
    -o "$TEST_OUTPUT" \
    -v

if [ -f "$TEST_OUTPUT" ]; then
    size=$(stat -c%s "$TEST_OUTPUT" 2>/dev/null || stat -f%z "$TEST_OUTPUT" 2>/dev/null)
    echo -e "${GREEN}✅ 测试 1 通过: 文件已下载 ($size bytes)${NC}"
    rm -f "$TEST_OUTPUT"
else
    echo -e "${RED}❌ 测试 1 失败: 文件未下载${NC}"
    exit 1
fi

echo ""
echo "测试 2: 使用 hf-mirror.com + IP 优选"
echo "-------------------------------------------------------------------"
python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --hf-endpoint https://hf-mirror.com \
    --optimize-hosts \
    --token "$TOKEN" \
    --no-cache \
    --mode direct \
    -o "$TEST_OUTPUT" \
    -v

if [ -f "$TEST_OUTPUT" ]; then
    size=$(stat -c%s "$TEST_OUTPUT" 2>/dev/null || stat -f%z "$TEST_OUTPUT" 2>/dev/null)
    echo -e "${GREEN}✅ 测试 2 通过: IP 优选模式下文件已下载 ($size bytes)${NC}"
    rm -f "$TEST_OUTPUT"
else
    echo -e "${RED}❌ 测试 2 失败: 文件未下载${NC}"
    exit 1
fi

echo ""
echo "测试 3: 环境变量 HF_ENDPOINT"
echo "-------------------------------------------------------------------"
export HF_ENDPOINT=https://hf-mirror.com

python -m xet.cli.main download \
    "$TEST_REPO/$TEST_FILE" \
    --token "$TOKEN" \
    --no-cache \
    --mode direct \
    -o "$TEST_OUTPUT" \
    -v

if [ -f "$TEST_OUTPUT" ]; then
    size=$(stat -c%s "$TEST_OUTPUT" 2>/dev/null || stat -f%z "$TEST_OUTPUT" 2>/dev/null)
    echo -e "${GREEN}✅ 测试 3 通过: 环境变量模式下文件已下载 ($size bytes)${NC}"
    rm -f "$TEST_OUTPUT"
else
    echo -e "${RED}❌ 测试 3 失败: 文件未下载${NC}"
    exit 1
fi

unset HF_ENDPOINT

echo ""
echo "======================================================================="
echo -e "${GREEN}✅ 所有测试通过！${NC}"
echo "======================================================================="
echo ""
echo "总结:"
echo "  1. ✅ --hf-endpoint 参数工作正常"
echo "  2. ✅ hf-mirror.com 可作为直连替代"
echo "  3. ✅ HF_ENDPOINT 环境变量支持"
echo "  4. ✅ IP 优选集成 HF_ENDPOINT 检测"
echo ""
