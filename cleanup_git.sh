#!/bin/bash

echo "🧹 开始清理 Git 历史中的大文件..."
echo ""

# 备份当前状态
echo "📦 创建备份..."
git branch backup-before-cleanup 2>/dev/null || true

# 使用 git filter-repo 清理（如果没有则使用 filter-branch）
if command -v git-filter-repo &> /dev/null; then
    echo "✓ 使用 git-filter-repo（推荐）"
    
    # 移除大文件
    git filter-repo --force \
        --path test_output_cli/ --invert-paths \
        --path debug_materials/ --invert-paths \
        --path '*.gguf' --invert-paths \
        --path test_output/ --invert-paths \
        --path test_output_2_7/ --invert-paths \
        --path test_output_batch_json/ --invert-paths \
        --path test_output_cli_p1/ --invert-paths \
        --path test_output_cli_p2/ --invert-paths \
        --path test_output_cli_p2_fixed/ --invert-paths \
        --path test_output_cli_p3/ --invert-paths \
        --path test_output_verify_cache/ --invert-paths \
        --path test_output_verify_cache2/ --invert-paths \
        --path test_glm_json/ --invert-paths
else
    echo "⚠️  git-filter-repo 未安装，使用 filter-branch（较慢）"
    
    # 使用 filter-branch 清理
    git filter-branch --force --index-filter \
        'git rm -r --cached --ignore-unmatch test_output_cli/ debug_materials/ test_output*/ test_glm_json/ *.gguf' \
        --prune-empty --tag-name-filter cat -- --all
fi

echo ""
echo "🗑️  清理引用和垃圾..."
rm -rf .git/refs/original/
git reflog expire --expire=now --all
git gc --prune=now --aggressive

echo ""
echo "📊 清理后的大小:"
du -sh .git

echo ""
echo "✅ Git 历史清理完成！"
echo ""
echo "⚠️  注意事项:"
echo "  1. 如果需要恢复，运行: git checkout backup-before-cleanup"
echo "  2. 如果确认无误，删除备份: git branch -D backup-before-cleanup"
echo "  3. 如果已推送到远程，需要强制推送: git push origin --force --all"
