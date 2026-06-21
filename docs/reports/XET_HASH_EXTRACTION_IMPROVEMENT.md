# XET Hash 提取逻辑改进

**日期**: 2026-06-21  
**问题**: xet-hash 提取逻辑过于严格，容易因服务器协议变化而失效

---

## 改进方案

### 原始逻辑（脆弱）

```python
# 只支持一种格式
match = re.search(r'<xet://([^>]+)>;\s*rel="xet-hash"', link_header)
```

**问题**:
- 硬编码格式，服务器改变就失效
- 不支持引号变化（`rel="xet-hash"` vs `rel='xet-hash'`）
- 不支持空格变化（`>;` vs `> ;`）
- 不支持大小写变化（`rel="xet-hash"` vs `rel="Xet-Hash"`）

### 改进逻辑（健壮）

```python
# 提取 xet-hash（支持多种格式，优先级从高到低）
xet_hash = None

# 方法1: 标准 xet:// 协议格式 (rel="xet-hash")
match = re.search(
    r'<xet://([0-9a-f]{64})[^>]*>(?:;|\s*;)\s*rel=["\']?xet-hash["\']?',
    link_header,
    re.IGNORECASE
)
if match:
    xet_hash = match.group(1)

# 方法2: reconstruction-info URL 中的 hash（更通用）
if not xet_hash:
    # 匹配: /reconstructions/{hash} 或 /reconstruction/{hash}
    # 不限定域名、版本号
    match = re.search(
        r'<https?://[^/]+/[^/]*/reconstructions?/([0-9a-f]{64})[^>]*>(?:;|\s*;)\s*rel=["\']?xet-reconstruction',
        link_header,
        re.IGNORECASE
    )
    if match:
        xet_hash = match.group(1)

# 方法3: 任何URL中的64字符hex串（最后的fallback）
if not xet_hash:
    match = re.search(
        r'<[^>]*?([0-9a-f]{64})[^>]*>(?:;|\s*;)\s*rel=["\']?xet',
        link_header,
        re.IGNORECASE
    )
    if match:
        xet_hash = match.group(1)
```

### 改进点

1. **大小写不敏感** - `re.IGNORECASE`
2. **引号灵活** - `["\']?` 支持双引号、单引号或无引号
3. **空格容忍** - `(?:;|\s*;)\s*` 支持 `>;` 或 `> ;`
4. **Hash验证** - `[0-9a-f]{64}` 确保是合法的64字符hex
5. **多种fallback** - 三种方法，逐步降低严格度
6. **域名无关** - 不限定 `huggingface.co` 或特定域名
7. **版本无关** - 不限定 `/v1/` 或特定版本号

---

## 测试案例

### 案例1: 标准格式
```
Link: <xet://abc123...>; rel="xet-hash"
→ 方法1匹配
```

### 案例2: HuggingFace当前格式
```
Link: <https://cas-server.xethub.hf.co/v1/reconstructions/abc123...>; rel="xet-reconstruction-info"
→ 方法2匹配
```

### 案例3: 未来可能的变化
```
Link: <https://new-domain.com/v2/reconstruction/abc123...>; rel='XET-Reconstruction-Info'
→ 方法2匹配（大小写不敏感、单引号、单数形式）
```

### 案例4: 极简格式
```
Link: <https://cdn.example.com/files/abc123...>;rel=xet-file
→ 方法3匹配（最后fallback）
```

---

## 当前HuggingFace实际返回

```
link: <https://huggingface.co/api/models/mykor/granite-embedding-97m-multilingual-r2-GGUF/xet-read-token/45ce642d3fab2033d167ec09641a159010f7d9d9>; rel="xet-auth", <https://cas-server.xethub.hf.co/v1/reconstructions/e0aacd103e054264f5ede71ce63218c1110363261720d4c50c689ec3245ceb02>; rel="xet-reconstruction-info"
```

**没有** `xet://...` 格式的hash！

---

## 建议

1. **立即应用改进版正则**
2. **添加单元测试** 覆盖各种格式
3. **记录协议版本** 在文档中记录已知的格式变化
4. **监控失败** 如果所有方法都失败，记录完整Link头用于分析
