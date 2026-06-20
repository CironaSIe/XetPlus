"""Xet 协议数据结构定义。

定义 XET 下载协议所需的所有核心数据类型，
包括 HTTP Range、Chunk 范围、Reconstruction 响应等。
"""
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
import re


@dataclass
class HttpRange:
    """HTTP Range (RFC 7233): [start, end] 两端都包含。

    Attributes:
        start: 起始字节位置（包含）
        end: 结束字节位置（包含）
    """
    start: int
    end: int

    def to_header(self) -> str:
        """转换为 HTTP Range header 字符串。

        Returns:
            如 "bytes=0-1023" 格式的字符串
        """
        return f"bytes={self.start}-{self.end}"

    def length(self) -> int:
        """计算范围长度（字节数）。

        Returns:
            包含的字节数
        """
        return self.end - self.start + 1


@dataclass
class ChunkRange:
    """Chunk 索引范围: [start, end) 左闭右开。

    用于描述文件在 xorb 中的 chunk 索引区间。

    Attributes:
        start: 起始 chunk 索引（包含）
        end: 结束 chunk 索引（不包含）
    """
    start: int
    end: int

    def length(self) -> int:
        """计算范围内的 chunk 数量。

        Returns:
            chunk 数量
        """
        return self.end - self.start

@dataclass
class CASReconstructionTerm:
    """Reconstruction API 返回的单个 term 描述。

    每个 term 描述文件的一个片段，引用某个 xorb 中的一段 chunk 范围。

    Attributes:
        hash: xorb 的 MerkleHash（64字符hex字符串）
        range: 该 term 在 xorb 中的 chunk 索引范围
        unpacked_length: 解压后的长度（字节）
    """
    hash: str
    range: ChunkRange
    unpacked_length: int

    @classmethod
    def from_dict(cls, d: dict) -> 'CASReconstructionTerm':
        """从字典创建实例（JSON 反序列化）。

        Args:
            d: 包含 hash, range, unpacked_length 的字典

        Returns:
            CASReconstructionTerm 实例
        """
        return cls(
            hash=d['hash'],
            range=ChunkRange(d['range']['start'], d['range']['end']),
            unpacked_length=d['unpacked_length']
        )

    def to_dict(self) -> dict:
        return {
            'hash': self.hash,
            'range': {'start': self.range.start, 'end': self.range.end},
            'unpacked_length': self.unpacked_length,
        }

@dataclass
class CASReconstructionFetchInfo:
    """单个 xorb 的下载信息。

    包含从 CAS 获取 xorb 数据所需的 URL 和范围信息。

    Attributes:
        url: presigned 下载 URL
        url_range: 在该 URL 中的 HTTP Range
        chunk_range: 该请求对应的 chunk 索引范围
    """
    url: str
    url_range: HttpRange
    chunk_range: ChunkRange

    @classmethod
    def from_dict(cls, d: dict) -> 'CASReconstructionFetchInfo':
        """从字典创建实例（JSON 反序列化）。

        Args:
            d: 包含 url, url_range, range 的字典

        Returns:
            CASReconstructionFetchInfo 实例
        """
        return cls(
            url=d['url'],
            url_range=HttpRange(d['url_range']['start'], d['url_range']['end']),
            chunk_range=ChunkRange(d['range']['start'], d['range']['end'])
        )

    def to_dict(self) -> dict:
        return {
            'url': self.url,
            'url_range': {'start': self.url_range.start, 'end': self.url_range.end},
            'range': {'start': self.chunk_range.start, 'end': self.chunk_range.end},
        }

@dataclass
class QueryReconstructionResponse:
    """Reconstruction API 的完整响应。

    Stage 1 返回的数据结构，描述如何重建文件。

    支持两种 API 版本的响应格式:
    - V1 格式: 使用 fetch_info 字段
    - V2 格式: 使用 xorbs 字段（多范围优化）

    Attributes:
        offset_into_first_range: 第一个 term 的起始字节偏移
        terms: 有序的 term 列表，按顺序描述文件的各个片段
        fetch_info: 每个 xorb 的下载信息字典 {xorb_hash: [fetch_infos]}
    """
    offset_into_first_range: int
    terms: List[CASReconstructionTerm]
    fetch_info: Dict[str, List[CASReconstructionFetchInfo]]

    @classmethod
    def from_dict(cls, d: dict) -> 'QueryReconstructionResponse':
        """从字典创建实例（JSON 反序列化），自动检测 V1 或 V2 格式。

        V1 Response 格式:
        {
          "offset_into_first_range": 0,
          "terms": [...],
          "fetch_info": {
            "<xorb_hash>": [{"url": ..., "url_range": {...}, "range": {...}}]
          }
        }

        V2 Response 格式 (XET.SPEC.md §3.1):
        {
          "offset_into_first_range": 0,
          "terms": [...],
          "xorbs": {
            "<xorb_hash>": [{
              "url": "...",
              "ranges": [
                {"chunks": {"start":0,"end":N}, "bytes": {"start":0,"end":E}}
              ]
            }]
          }
        }

        Args:
            d: 响应 JSON 字典

        Returns:
            QueryReconstructionResponse 实例

        Raises:
            ValueError: 如果无法识别格式或缺少必要字段
        """
        # 检测版本
        if 'xorbs' in d and 'fetch_info' not in d:
            # V2 格式：需要转换 xorbs → fetch_info
            return cls._from_v2_dict(d)
        elif 'fetch_info' in d:
            # V1 格式：直接解析
            return cls._from_v1_dict(d)
        else:
            raise ValueError(
                "[Xet] 无法识别的 reconstruction 响应格式: "
                f"缺少 'fetch_info' 和 'xorbs' 字段"
            )

    @classmethod
    def _from_v1_dict(cls, d: dict) -> 'QueryReconstructionResponse':
        """从 V1 格式字典创建实例。"""
        return cls(
            offset_into_first_range=d.get('offset_into_first_range', 0),
            terms=[CASReconstructionTerm.from_dict(t) for t in d['terms']],
            fetch_info={
                k: [CASReconstructionFetchInfo.from_dict(fi) for fi in v]
                for k, v in d['fetch_info'].items()
            }
        )

    @classmethod
    def _from_v2_dict(cls, d: dict) -> 'QueryReconstructionResponse':
        """从 V2 格式字典创建实例（自动转换 xorbs → fetch_info）。

        转换逻辑:
        V2 的 xorbs[xorb_hash][i].ranges[j] 包含:
          - chunks: ChunkRange {start, end}
          - bytes: HttpRange {start, end} （闭区间！）

        需要转换为 V1 的 CASReconstructionFetchInfo 格式。
        """
        import logging
        logger = logging.getLogger(__name__)

        logger.debug("[Xet] 检测到 V2 response 格式，正在转换...")

        fetch_info_converted = {}

        for xorb_hash, xorb_entries in d.get('xorbs', {}).items():
            fetch_infos = []

            for entry_idx, entry in enumerate(xorb_entries):
                url = entry['url']

                # V2 可能包含多个 ranges（多范围请求）
                for range_idx, range_desc in enumerate(entry.get('ranges', [])):
                    chunk_range_data = range_desc['chunks']
                    byte_range_data = range_desc['bytes']

                    logger.debug(
                        f"[V2→V1] xorb={xorb_hash[:16]}..., "
                        f"entry={entry_idx}, range={range_idx}: "
                        f"chunks=[{chunk_range_data['start']},{chunk_range_data['end']}), "
                        f"bytes=[{byte_range_data['start']},{byte_range_data['end']}]"
                    )

                    fetch_info = CASReconstructionFetchInfo(
                        url=url,
                        url_range=HttpRange(
                            start=byte_range_data['start'],
                            end=byte_range_data['end']
                        ),
                        chunk_range=ChunkRange(
                            start=chunk_range_data['start'],
                            end=chunk_range_data['end']
                        )
                    )
                    fetch_infos.append(fetch_info)

            fetch_info_converted[xorb_hash] = fetch_infos

        # ✅ C2 修复: 检测 V2 返回中缺失的 xorb（term 引用但 xorbs 字典无对应 entry）
        # 注意: 此时 result 尚未创建，需从原始 d['terms'] 提取 hash
        term_hashes = {t.get('hash', '') for t in d.get('terms', [])}
        missing_hashes = term_hashes - set(fetch_info_converted.keys())
        if missing_hashes:
            logger.warning(
                f"[V2→V1] ⚠️ {len(missing_hashes)} 个 term 引用的 xorb "
                f"在 V2 xorbs 字段中无下载信息: "
                f"{[h[:16] for h in list(missing_hashes)[:5]]}"
            )
            for h in missing_hashes:
                fetch_info_converted[h] = []  # 空列表让下游明确报错而非 KeyError

        logger.debug(f"[Xet] V2→V1 转换完成: {len(fetch_info_converted)} 个 xorb")

        return cls(
            offset_into_first_range=d.get('offset_into_first_range', 0),
            terms=[CASReconstructionTerm.from_dict(t) for t in d['terms']],
            fetch_info=fetch_info_converted
        )

    def to_dict(self) -> dict:
        return {
            'offset_into_first_range': self.offset_into_first_range,
            'terms': [t.to_dict() for t in self.terms],
            'fetch_info': {
                k: [fi.to_dict() for fi in v]
                for k, v in self.fetch_info.items()
            },
        }

@dataclass
class XorbBlockData:
    """解压后的 xorb 数据块。

    反序列化一个完整的 xorb 后得到的结果。

    Attributes:
        chunk_offsets: chunk 索引到字节偏移的映射列表 [(chunk_idx, byte_offset), ...]
        data: 所有解压后 chunk 的拼接数据
    """
    chunk_offsets: List[Tuple[int, int]]
    data: bytes


@dataclass
class XetTokenInfo:
    """CAS JWT Token 信息。

    从 HuggingFace 获取的用于访问 CAS 服务的 token。

    Attributes:
        access_token: JWT access token 字符串
        endpoint: CAS 服务的基础 URL（如 https://cas-server.xethub.hf.co）
        expiration: token 过期时间戳（Unix 秒）
    """
    access_token: str
    endpoint: str
    expiration: int


@dataclass
class XetFileInfo:
    """从 HEAD 请求获取的 XET 文件元数据。

    封装检测 Xet 文件时获取的所有关键信息。

    Attributes:
        xet_hash: 文件的 MerkleHash（Xet hash），64字符hex
        sha256: 文件的 SHA256 哈希值
        size: 文件大小（字节）
        location: presigned 直接下载 URL（可选，用于方案A快速路径）
        auth_url: xet-auth URL（获取 CAS token）
        recon_url: reconstruction API URL
        repo_commit: Git commit hash
    """
    xet_hash: str
    sha256: str
    size: int
    location: Optional[str] = None
    auth_url: Optional[str] = None
    recon_url: Optional[str] = None
    repo_commit: Optional[str] = None

    @classmethod
    def from_headers(cls, headers: dict) -> 'XetFileInfo':
        """从 HTTP 响应 headers 创建实例。

        解析 HEAD 请求返回的各种 Xet 相关 header。

        Args:
            headers: HTTP 响应头字典

        Returns:
            XetFileInfo 实例

        Raises:
            ValueError: 如果缺少必要的 X-Xet-Hash header
        """
        xet_hash = headers.get('X-Xet-Hash') or headers.get('x-xet-hash')
        if not xet_hash:
            raise ValueError("Missing X-Xet-Hash header")

        # 提取 SHA256（带引号的 ETag）
        linked_etag = headers.get('X-Linked-ETag', '') or headers.get('x-linked-etag', '')
        sha256 = linked_etag.strip('"') if linked_etag else ''

        # 提取文件大小
        size_str = headers.get('X-Linked-Size') or headers.get('x-linked-size', '0')
        try:
            size = int(size_str)
        except ValueError:
            size = 0

        # Location header（presigned URL，用于直接下载）
        location = headers.get('Location') or headers.get('location')

        # Link header（包含 auth 和 recon URL）
        link_header = headers.get('Link', '') or headers.get('link', '')
        auth_url, recon_url = cls._parse_link_header(link_header)

        repo_commit = headers.get('X-Repo-Commit') or headers.get('x-repo-commit')

        return cls(
            xet_hash=xet_hash,
            sha256=sha256,
            size=size,
            location=location,
            auth_url=auth_url,
            recon_url=recon_url,
            repo_commit=repo_commit
        )

    @staticmethod
    def _parse_link_header(link_header: str) -> Tuple[Optional[str], Optional[str]]:
        """解析 HTTP Link header 提取 xet-auth 和 xet-reconstruction-info URL。

        Link header 格式示例：
        <https://huggingface.co/api/.../xet-read-token/abc123>; rel="xet-auth",
        <https://cas-server.xethub.hf.co/...>; rel="xet-reconstruction-info"

        Args:
            link_header: Link header 的原始字符串

        Returns:
            (auth_url, recon_url) 元组，未找到则为 None
        """
        if not link_header:
            return None, None

        auth_url = None
        recon_url = None

        # 使用正则表达式匹配所有 link 条目
        pattern = r'<([^>]+)>;\s*rel="([^"]+)"'
        matches = re.findall(pattern, link_header)

        for url, rel in matches:
            if rel == 'xet-auth':
                auth_url = url
            elif rel == 'xet-reconstruction-info':
                recon_url = url

        return auth_url, recon_url

    def is_direct_download_available(self) -> bool:
        """检查是否可以使用方案A（直接下载）。

        Returns:
            如果有 Location presigned URL 则返回 True
        """
        return self.location is not None

@dataclass
class XetTokenInfo:
    """CAS JWT Token 信息。

    从 HuggingFace 获取的用于访问 CAS 服务的 token。

    Attributes:
        access_token: JWT access token 字符串
        endpoint: CAS 服务的基础 URL（如 https://cas.huggingface.co）
        expiration: token 过期时间戳（Unix 时间）
    """
    access_token: str
    endpoint: str
    expiration: int
