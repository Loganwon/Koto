# -*- coding: utf-8 -*-
"""
doc_chunker.py — 长文档分块与检索模块
======================================

提供两个主要功能:
1. DocChunker.chunk(text)    — 按段落/句子边界分块，返回 List[str]
2. DocChunker.retrieve(chunks, query, top_k) — 基于 TF-IDF / n-gram 相似度
   从分块列表中检索最相关的 top_k 段，返回按原始顺序排列（保持上下文连贯）

用法 (socket_handler.py 中):
    from app.core.file.doc_chunker import DocChunker

    if len(full_text) > DocChunker.CHUNK_THRESHOLD:
        chunks = DocChunker.chunk(full_text)
        retrieved = DocChunker.retrieve(chunks, query=user_prompt, top_k=4)
        context_text = "\n\n---\n\n".join(retrieved)
    else:
        context_text = full_text
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import List, Tuple

# ── 超过此字符数则启用 RAG 路径 ─────────────────────────────────────────────
CHUNK_THRESHOLD = 8000  # chars — 约等于 2000 个中文字
CHUNK_SIZE = 1800  # chars per chunk target
CHUNK_OVERLAP = 200  # overlap chars between adjacent chunks


class DocChunker:
    """长文档分块 + 轻量本地检索引擎。"""

    CHUNK_THRESHOLD = CHUNK_THRESHOLD

    # ─────────────────────────────────────────────────────────────────────────
    # 1. 分块
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def chunk(
        text: str,
        chunk_size: int = CHUNK_SIZE,
        overlap: int = CHUNK_OVERLAP,
    ) -> List[str]:
        """
        按段落边界将 text 切成若干块，相邻块之间保留 overlap 个字符的重叠。

        优先在段落（空行）处切割；若单段落超过 chunk_size 则在句子边界（。！？\n）
        处进一步切割。
        """
        if not text:
            return []

        # Step 1: 按空行拆成段落
        paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]

        chunks: List[str] = []
        current_parts: List[str] = []
        current_len = 0

        for para in paragraphs:
            # 段落本身超长 → 先切句子
            if len(para) > chunk_size:
                sub_sentences = DocChunker._split_sentences(para)
                for sent in sub_sentences:
                    if current_len + len(sent) > chunk_size and current_parts:
                        chunks.append("\n".join(current_parts))
                        # 保留 overlap：从末尾反向收集
                        overlap_parts = DocChunker._collect_overlap(
                            current_parts, overlap
                        )
                        current_parts = overlap_parts
                        current_len = sum(len(p) for p in current_parts)
                    current_parts.append(sent)
                    current_len += len(sent)
            else:
                if current_len + len(para) > chunk_size and current_parts:
                    chunks.append("\n".join(current_parts))
                    overlap_parts = DocChunker._collect_overlap(current_parts, overlap)
                    current_parts = overlap_parts
                    current_len = sum(len(p) for p in current_parts)
                current_parts.append(para)
                current_len += len(para)

        if current_parts:
            chunks.append("\n".join(current_parts))

        return chunks

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        """将长段文本在句子边界处切分（中英文标点）。"""
        parts = re.split(r"(?<=[。！？!?\n])", text)
        return [p for p in parts if p.strip()]

    @staticmethod
    def _collect_overlap(parts: List[str], overlap: int) -> List[str]:
        """从 parts 末尾反向收集不超过 overlap 字符的段落，保持顺序。"""
        result: List[str] = []
        total = 0
        for p in reversed(parts):
            if total + len(p) > overlap:
                break
            result.insert(0, p)
            total += len(p)
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # 2. 检索
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def retrieve(
        chunks: List[str],
        query: str,
        top_k: int = 4,
    ) -> List[str]:
        """
        用 TF-IDF 余弦相似度从 chunks 中检索与 query 最相关的 top_k 个块，
        返回结果按原始段落顺序排列（保持叙事/逻辑连贯性）。
        """
        if not chunks or not query:
            return chunks[:top_k]

        query_terms = DocChunker._tokenize(query)
        if not query_terms:
            return chunks[:top_k]

        # 构建整个语料的词频表
        doc_tfs: List[Counter] = [Counter(DocChunker._tokenize(c)) for c in chunks]
        n_docs = len(doc_tfs)

        # DF（文档频率）
        df: Counter = Counter()
        for tf in doc_tfs:
            for term in tf:
                df[term] += 1

        def _tfidf_vec(tf: Counter) -> dict:
            vec = {}
            total = sum(tf.values()) or 1
            for term, cnt in tf.items():
                idf = math.log((n_docs + 1) / (df[term] + 1)) + 1.0
                vec[term] = (cnt / total) * idf
            return vec

        def _cosine(a: dict, b: dict) -> float:
            common = set(a) & set(b)
            if not common:
                return 0.0
            dot = sum(a[t] * b[t] for t in common)
            mag_a = math.sqrt(sum(v * v for v in a.values()))
            mag_b = math.sqrt(sum(v * v for v in b.values()))
            if mag_a == 0 or mag_b == 0:
                return 0.0
            return dot / (mag_a * mag_b)

        query_vec = _tfidf_vec(Counter(query_terms))
        scored: List[Tuple[int, float]] = []
        for idx, tf in enumerate(doc_tfs):
            score = _cosine(query_vec, _tfidf_vec(tf))
            scored.append((idx, score))

        # 选出 top_k 个，按原始顺序排回来
        top_indices = sorted(
            [idx for idx, _ in sorted(scored, key=lambda x: x[1], reverse=True)[:top_k]]
        )
        return [chunks[i] for i in top_indices]

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """
        极简分词：保留 CJK 字符（每字一 token）+ 英文单词（小写）。
        不依赖任何第三方分词库，保证零额外依赖。
        """
        tokens: List[str] = []
        # CJK 字符逐字
        for ch in re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]", text):
            tokens.append(ch)
        # ASCII 单词
        for word in re.findall(r"[a-zA-Z0-9]+", text):
            tokens.append(word.lower())
        return tokens
