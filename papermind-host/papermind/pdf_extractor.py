"""
Phase 2.2: PDF 文本提取核心模块

提供 PDF 上传与文本提取能力：
- 使用 PyMuPDF (fitz) 提取 PDF 文本
- 自动识别论文标题（元数据或首页）
- 检测并提示不支持的 PDF 类型（加密、扫描版、损坏）
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PDFExtractResult:
    """PDF 提取结果"""

    success: bool
    title: str | None  # 从元数据或首页提取的标题
    text: str | None  # 提取的全文
    preview: str | None  # 前 500 字符预览
    error_message: str | None  # 失败时的错误信息
    error_code: str | None  # 错误码：encrypted | scanned | corrupted | empty | unknown


async def extract_pdf_text(
    pdf_path: Path,
    max_chars: int = 50000,
    preview_chars: int = 500,
) -> PDFExtractResult:
    """
    从 PDF 中提取文本内容

    Args:
        pdf_path: PDF 文件路径
        max_chars: 最大提取字符数（防止超大文件）
        preview_chars: 预览字符数

    Returns:
        PDFExtractResult: 提取结果
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return PDFExtractResult(
            success=False,
            title=None,
            text=None,
            preview=None,
            error_message="PyMuPDF 未安装，请运行：pip install PyMuPDF",
            error_code="missing_dependency",
        )

    try:
        # 打开 PDF 文件
        doc = fitz.open(pdf_path)

        # 检查加密
        if doc.is_encrypted:
            doc.close()
            return PDFExtractResult(
                success=False,
                title=None,
                text=None,
                preview=None,
                error_message="PDF 已加密，无法提取文本",
                error_code="encrypted",
            )

        # 提取标题（优先从元数据，否则从首页）
        title = _extract_title(doc)

        # 提取全文
        text_parts = []
        total_chars = 0

        for page_num in range(len(doc)):
            page = doc[page_num]
            page_text = page.get_text()

            # 累积字符数
            total_chars += len(page_text)
            text_parts.append(page_text)

            # 达到最大字符限制
            if total_chars >= max_chars:
                break

        doc.close()

        # 合并全文
        full_text = "\n".join(text_parts)

        # 检测是否为扫描版（文本极少）
        if len(full_text.strip()) < 100 and len(doc) > 1:
            return PDFExtractResult(
                success=False,
                title=title,
                text=None,
                preview=None,
                error_message="检测到扫描版 PDF，暂不支持 OCR",
                error_code="scanned",
            )

        # 检测空文本
        if not full_text.strip():
            return PDFExtractResult(
                success=False,
                title=title,
                text=None,
                preview=None,
                error_message="未能提取到文本内容",
                error_code="empty",
            )

        # 生成预览
        preview = full_text[:preview_chars] + ("..." if len(full_text) > preview_chars else "")

        return PDFExtractResult(
            success=True,
            title=title,
            text=full_text,
            preview=preview,
            error_message=None,
            error_code=None,
        )

    except Exception as e:
        return PDFExtractResult(
            success=False,
            title=None,
            text=None,
            preview=None,
            error_message=f"PDF 处理失败：{str(e)}",
            error_code="corrupted",
        )


def _extract_title(doc) -> str | None:
    """
    从 PDF 元数据或首页提取标题

    Args:
        doc: PyMuPDF Document 对象

    Returns:
        提取的标题，失败返回 None
    """
    # 1. 尝试从元数据提取
    metadata = doc.metadata
    if metadata and metadata.get("title"):
        title = metadata["title"].strip()
        if title and len(title) > 3:  # 有效标题至少 3 个字符
            return title

    # 2. 尝试从首页提取（启发式）
    if len(doc) > 0:
        first_page = doc[0]
        page_text = first_page.get_text()

        # 提取前几行非空文本
        lines = [line.strip() for line in page_text.split("\n") if line.strip()]

        if lines:
            # 启发式：取前 3 行中最长的一行作为标题候选
            candidates = lines[:3]
            longest = max(candidates, key=len)

            # 验证标题长度合理（10-200 字符）
            if 10 <= len(longest) <= 200:
                # 清理标题（移除多余空格和特殊字符）
                title = re.sub(r"\s+", " ", longest).strip()
                return title

    return None
