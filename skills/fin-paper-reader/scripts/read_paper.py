#!/usr/bin/env python3
"""
论文 / 研报 PDF 文本提取工具

功能：
  1. 从 PDF 文件中提取全文文本
  2. 提取首页截图（可选）
  3. 输出基本统计信息（页数、字数、语言检测）

用法：
  python read_paper.py <pdf_path> [--screenshot] [--output-dir <dir>]

依赖：
  pip install pypdf Pillow

来源参考：
  RD-Agent/rdagent/components/document_reader/document_reader.py
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path


def extract_text_from_pdf(pdf_path: str) -> dict:
    """
    从 PDF 文件中提取文本。

    返回:
        {
            "file": "文件名",
            "total_pages": 页数,
            "pages": [{"page": 1, "text": "..."}, ...],
            "full_text": "全文拼接",
            "char_count": 字符数,
            "detected_language": "zh" | "en" | "mixed",
        }
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader
        except ImportError:
            print("ERROR: 需要安装 pypdf: pip install pypdf", file=sys.stderr)
            sys.exit(1)

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        print(f"ERROR: 文件不存在: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    reader = PdfReader(str(pdf_path))
    pages = []
    full_text_parts = []

    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        pages.append({"page": i + 1, "text": text})
        full_text_parts.append(text)

    full_text = "\n\n".join(full_text_parts)

    # 语言检测（简单启发式）
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", full_text))
    total_chars = len(full_text.strip())
    if total_chars == 0:
        detected_lang = "unknown"
    elif chinese_chars / max(total_chars, 1) > 0.1:
        detected_lang = "zh" if chinese_chars / max(total_chars, 1) > 0.3 else "mixed"
    else:
        detected_lang = "en"

    return {
        "file": pdf_path.name,
        "total_pages": len(reader.pages),
        "pages": pages,
        "full_text": full_text,
        "char_count": total_chars,
        "detected_language": detected_lang,
    }


def extract_first_page_screenshot(pdf_path: str, output_path: str) -> str | None:
    """
    提取 PDF 首页为 PNG 截图。

    依赖: pip install pymupdf (fitz)
    如果未安装 pymupdf 则跳过并返回 None。
    """
    try:
        import fitz  # pymupdf
    except ImportError:
        print("WARN: pymupdf 未安装，跳过首页截图 (pip install pymupdf)", file=sys.stderr)
        return None

    doc = fitz.open(pdf_path)
    if len(doc) == 0:
        return None

    page = doc[0]
    # 2x 分辨率
    mat = fitz.Matrix(2, 2)
    pix = page.get_pixmap(matrix=mat)
    pix.save(output_path)
    doc.close()
    return output_path


def truncate_text(text: str, max_chars: int = 80000) -> str:
    """截断过长文本，保留首尾各一半。"""
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + "\n\n... [文本过长，已截断中间部分] ...\n\n" + text[-half:]


def main():
    parser = argparse.ArgumentParser(description="PDF 论文/研报文本提取")
    parser.add_argument("pdf_path", help="PDF 文件路径")
    parser.add_argument("--screenshot", action="store_true", help="提取首页截图")
    parser.add_argument("--output-dir", default=None, help="输出目录（默认: PDF 同目录）")
    parser.add_argument("--max-chars", type=int, default=80000, help="文本最大字符数（截断阈值）")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path).resolve()
    output_dir = Path(args.output_dir) if args.output_dir else pdf_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. 提取文本
    result = extract_text_from_pdf(str(pdf_path))

    # 2. 截断
    result["full_text_truncated"] = truncate_text(result["full_text"], args.max_chars)
    result["was_truncated"] = len(result["full_text"]) > args.max_chars

    # 3. 首页截图（可选）
    screenshot_path = None
    if args.screenshot:
        screenshot_file = output_dir / f"{pdf_path.stem}_page1.png"
        screenshot_path = extract_first_page_screenshot(str(pdf_path), str(screenshot_file))
        result["screenshot"] = screenshot_path

    # 4. 保存提取的文本
    text_output = output_dir / f"{pdf_path.stem}_extracted.txt"
    with open(text_output, "w", encoding="utf-8") as f:
        f.write(result["full_text"])
    result["text_output_path"] = str(text_output)

    # 5. 输出
    if args.json:
        # JSON 模式：输出元数据（不含 pages 和 full_text 避免过大）
        meta = {k: v for k, v in result.items() if k not in ("pages", "full_text", "full_text_truncated")}
        print(json.dumps(meta, ensure_ascii=False, indent=2))
    else:
        print(f"📄 文件: {result['file']}")
        print(f"📖 页数: {result['total_pages']}")
        print(f"📝 字符数: {result['char_count']}")
        print(f"🌐 语言: {result['detected_language']}")
        if result["was_truncated"]:
            print(f"✂️  文本已截断至 {args.max_chars} 字符")
        print(f"💾 文本已保存: {text_output}")
        if screenshot_path:
            print(f"📸 首页截图: {screenshot_path}")

    return result


if __name__ == "__main__":
    main()
