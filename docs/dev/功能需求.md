# XET+ 功能需求

## 🎯 分段校验与修复功能

**提出日期**: 2026-06-21  
**优先级**: 中  
**状态**: 待设计

### 需求描述

当下载完成后发现整体 HASH 不正确时，希望能够：
1. **分段校验**：利用 CAS reconstruction API，将文件分段进行校验
2. **定位错误区域**：找出哪些区域的数据是错误的
3. **选择性重下载**：只重新下载并覆盖错误的段
4. **断点续传增强**：如果前 40% 都正确，后面全错，能否从 40% 开始重新下载

### 使用场景

**场景 1: 网络不稳定导致部分数据损坏**
```bash
$ python xet_dl.py download repo/model file.bin -o output.bin
✅ 下载完成: 1.5 GB
❌ 文件校验失败: BLAKE3 hash 不匹配

$ python xet_dl.py verify output.bin --repair
📊 分段校验中...
  ✅ Segment 0-10: 正确
  ✅ Segment 11-20: 正确
  ❌ Segment 21-25: 损坏
  ✅ Segment 26-30: 正确
  
🔧 重新下载损坏的段...
✅ 修复完成: 重新下载 5/31 段 (16%)
✅ 最终校验通过
```

**场景 2: 中断后部分恢复**
```bash
$ python xet_dl.py download repo/model file.bin -o output.bin
^C 用户中断 (已下载 40%)

$ python xet_dl.py verify output.bin --analyze
📊 完整性分析:
  ✅ 0-40%: 已验证正确 (600 MB)
  ❓ 40-100%: 未下载或损坏 (900 MB)
  
$ python xet_dl.py download repo/model file.bin -o output.bin --resume --verify-first
📊 校验现有数据...
  ✅ 前 40% 正确，从 40% 继续下载
⬇️  下载中: 40% -> 100%
✅ 下载完成并校验通过
```

### 技术设计

#### 1. 分段校验原理

利用 XET 的 Term 结构进行分段校验：
- 每个 Term 对应文件的一段连续数据
- Term 包含该段数据的预期 BLAKE3 hash
- 可以逐 Term 校验，定位具体哪个 Term 的数据错误

```python
def verify_file_by_terms(
    file_path: Path,
    recon: QueryReconstructionResponse,
) -> List[TermVerifyResult]:
    """逐 Term 校验文件。
    
    Returns:
        每个 Term 的校验结果列表
    """
    results = []
    with open(file_path, 'rb') as f:
        current_offset = 0
        
        for term_idx, term in enumerate(recon.terms):
            # 读取该 Term 对应的文件数据
            f.seek(current_offset)
            term_data = f.read(term.unpacked_length)
            
            # 计算 BLAKE3 hash
            actual_hash = blake3(term_data).hexdigest()
            expected_hash = term.hash  # Term 的预期 hash
            
            result = TermVerifyResult(
                term_idx=term_idx,
                offset=current_offset,
                length=term.unpacked_length,
                expected_hash=expected_hash,
                actual_hash=actual_hash,
                is_valid=(actual_hash == expected_hash)
            )
            results.append(result)
            current_offset += term.unpacked_length
    
    return results
```

#### 2. 选择性修复

只重新下载损坏的 Terms：

```python
def repair_corrupted_terms(
    file_path: Path,
    recon: QueryReconstructionResponse,
    verify_results: List[TermVerifyResult],
    cas_client: CASClient,
):
    """修复损坏的 Terms。"""
    corrupted_terms = [r for r in verify_results if not r.is_valid]
    
    if not corrupted_terms:
        logger.info("✅ 文件完整，无需修复")
        return
    
    logger.info(f"🔧 发现 {len(corrupted_terms)}/{len(verify_results)} 个损坏的 Terms")
    
    with open(file_path, 'r+b') as f:
        for result in corrupted_terms:
            term_idx = result.term_idx
            term = recon.terms[term_idx]
            
            logger.info(f"  重新下载 Term {term_idx}...")
            
            # 重建该 Term 的数据
            term_data = reconstruct_single_term(term, recon, cas_client)
            
            # 覆盖写入文件
            f.seek(result.offset)
            f.write(term_data)
            
            logger.info(f"  ✅ Term {term_idx} 修复完成")
```

#### 3. 增强的断点续传

在恢复时先校验现有数据：

```python
def resume_with_verification(
    file_path: Path,
    recon: QueryReconstructionResponse,
    cas_client: CASClient,
):
    """带校验的断点续传。"""
    if not file_path.exists():
        # 文件不存在，从头下载
        return download_from_scratch(file_path, recon, cas_client)
    
    # 校验现有数据
    logger.info("📊 校验现有数据...")
    verify_results = verify_file_by_terms(file_path, recon)
    
    # 找到第一个错误的 Term
    first_corrupted_idx = None
    for result in verify_results:
        if not result.is_valid:
            first_corrupted_idx = result.term_idx
            break
    
    if first_corrupted_idx is None:
        logger.info("✅ 文件已完整下载并校验通过")
        return
    
    # 从第一个错误的 Term 开始下载
    valid_percentage = (first_corrupted_idx / len(verify_results)) * 100
    logger.info(
        f"✅ 前 {valid_percentage:.1f}% 数据正确\n"
        f"⬇️  从 Term {first_corrupted_idx} 继续下载..."
    )
    
    # 继续下载
    download_from_term(
        file_path, recon, cas_client,
        start_term_idx=first_corrupted_idx
    )
```

#### 4. CLI 接口设计

```bash
# 校验文件完整性
python xet_dl.py verify <file> [--repo REPO] [--path PATH]
  --repo, --path: 用于获取 reconstruction 信息
  --repair: 自动修复损坏的段
  --analyze: 只分析不修复

# 带校验的断点续传
python xet_dl.py download REPO PATH -o OUTPUT --resume --verify-first
  --verify-first: 恢复前先校验现有数据
```

### 实现优先级

1. **P0 (高)**: 分段校验功能 - `verify_file_by_terms()`
2. **P1 (高)**: 选择性修复功能 - `repair_corrupted_terms()`
3. **P2 (中)**: 增强断点续传 - `resume_with_verification()`
4. **P3 (低)**: CLI 接口封装 - `verify` 子命令

### 技术挑战

1. **Term vs Chunk 粒度**
   - Term 是重建层面的单位，粒度较粗
   - Chunk 是存储层面的单位，粒度更细
   - 需要权衡校验粒度和效率

2. **部分 Term 损坏**
   - 一个 Term 可能依赖多个 Xorbs
   - 如何定位是哪个 Xorb 的数据损坏？

3. **并发安全**
   - 修复时需要原地覆盖文件
   - 需要确保 seek + write 的原子性

### 参考实现

- Rust 原版可能有类似功能
- Git LFS 的 `git lfs fsck` 命令
- 分布式文件系统的 scrub 功能

### 后续工作

- [ ] 调研 Rust 原版是否有类似功能
- [ ] 设计详细的 API 接口
- [ ] 实现 P0: 分段校验
- [ ] 实现 P1: 选择性修复
- [ ] 编写单元测试和集成测试
- [ ] 更新用户文档

---

**提出者**: User  
**记录者**: Claude  
**优先级评估**: 中（非核心功能，但对容错性有显著提升）
