#!/data/data/com.termux/files/usr/bin/bash
# 测试批量下载 JSON 文件 - 使用 zai-org/GLM-5.2 仓库

set -e

TOKEN="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"
PROXY="http://127.0.0.1:12334"
TEST_REPO="zai-org/GLM-5.2"
OUTPUT_DIR="test_output_batch_json"

# 颜色
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "=========================================="
echo "测试批量下载 JSON 文件"
echo "=========================================="
echo ""
echo -e "${BLUE}仓库:${NC} $TEST_REPO"
echo -e "${BLUE}过滤:${NC} *.json"
echo -e "${BLUE}输出:${NC} $OUTPUT_DIR"
echo ""

# 清理旧输出
rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"

echo -e "${BLUE}执行批量下载...${NC}"
python -m xet.cli.main download \
    "$TEST_REPO" \
    --include "*.json" \
    --token "$TOKEN" \
    --proxy "$PROXY" \
    --no-cache \
    -o "$OUTPUT_DIR/" \
    2>&1 | tee batch_json_download.log

echo ""
echo "=========================================="
echo "下载结果"
echo "=========================================="

# 统计结果
json_count=$(find "$OUTPUT_DIR" -name "*.json" -type f 2>/dev/null | wc -l)
total_size=$(du -sh "$OUTPUT_DIR" 2>/dev/null | awk '{print $1}')

if [ $json_count -gt 0 ]; then
    echo -e "${GREEN}✅ 成功下载 $json_count 个 JSON 文件${NC}"
    echo -e "${BLUE}总大小:${NC} $total_size"
    echo ""
    echo "文件列表:"
    find "$OUTPUT_DIR" -name "*.json" -type f -exec ls -lh {} \; | awk '{print "  " $9 " (" $5 ")"}'
else
    echo -e "${RED}❌ 未找到 JSON 文件${NC}"
    exit 1
fi
