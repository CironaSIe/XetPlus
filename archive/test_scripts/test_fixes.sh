#!/bin/bash
# 测试修复后的参数和日志功能

echo "=== 测试 1: 验证参数别名 ==="
echo "测试 --concurrent 参数..."
python3 -m xet.cli.main download --help | grep -E "concurrent|concurrency" | head -2

echo ""
echo "=== 测试 2: 验证新增参数 ==="
echo "测试 --prefetch-max..."
python3 -m xet.cli.main download --help | grep "prefetch-max" -A 1

echo ""
echo "测试 --checkpoint-interval..."
python3 -m xet.cli.main download --help | grep "checkpoint-interval" -A 1

echo ""
echo "测试 --retry-max..."
python3 -m xet.cli.main download --help | grep "retry-max" -A 1

echo ""
echo "=== 测试 3: 验证日志文件创建 ==="
LOG_FILE="./test_log_$(date +%s).log"
echo "创建测试日志文件: $LOG_FILE"
python3 -m xet.cli.main --log-file "$LOG_FILE" download --help > /dev/null 2>&1
if [ -f "$LOG_FILE" ]; then
    echo "✓ 日志文件创建成功: $LOG_FILE"
    echo "日志内容预览:"
    head -5 "$LOG_FILE"
    rm "$LOG_FILE"
else
    echo "✗ 日志文件创建失败"
fi

echo ""
echo "=== 测试 4: 参数完整性对比 ==="
echo "xetplus 参数统计:"
python3 -m xet.cli.main download --help 2>&1 | grep -E "^\s*--" | wc -l

echo ""
echo "=== 所有测试完成 ==="
