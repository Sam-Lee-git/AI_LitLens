from __future__ import annotations

import hashlib
import io
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import fitz
from bs4 import BeautifulSoup
from ebooklib import ITEM_DOCUMENT, epub
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Project, ProjectStatus, Source, SourceBlock


class IngestionError(ValueError):
    pass


@dataclass(slots=True)
class ExtractedBlock:
    locator: dict
    text: str


def _clean_text(value: str) -> str:
    value = value.replace("\u0000", " ").replace("\r\n", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _detect_type(filename: str, payload: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf" and payload.startswith(b"%PDF-"):
        return "pdf"
    if suffix == ".epub" and payload.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                mimetype = archive.read("mimetype").decode("ascii", errors="ignore").strip()
            if mimetype == "application/epub+zip":
                return "epub"
        except (KeyError, zipfile.BadZipFile):
            pass
    raise IngestionError("只支持内容有效的 .pdf 或 .epub 文件，扩展名和文件内容必须一致。")


def _extract_pdf(payload: bytes) -> list[ExtractedBlock]:
    try:
        document = fitz.open(stream=payload, filetype="pdf")
    except Exception as exc:
        raise IngestionError("PDF 无法打开或已经损坏。") from exc
    blocks: list[ExtractedBlock] = []
    total_chars = 0
    for page_index in range(document.page_count):
        page_text = _clean_text(document.load_page(page_index).get_text("text"))
        if page_text:
            total_chars += len(page_text)
            blocks.append(
                ExtractedBlock(
                    locator={
                        "type": "pdf",
                        "page_start": page_index + 1,
                        "page_end": page_index + 1,
                    },
                    text=page_text,
                )
            )
    if document.page_count and total_chars < max(80, document.page_count * 10):
        raise IngestionError("这个 PDF 几乎没有可提取文字，可能是扫描件；MVP 暂不支持 OCR。")
    if not blocks:
        raise IngestionError("PDF 中没有可提取文字。")
    return blocks


def _chapter_title(soup: BeautifulSoup, fallback: str) -> str:
    heading = soup.find(["h1", "h2", "h3", "title"])
    return _clean_text(heading.get_text(" "))[:160] if heading else fallback


def _extract_epub(path: Path) -> list[ExtractedBlock]:
    try:
        book = epub.read_epub(str(path))
    except Exception as exc:
        raise IngestionError("EPUB 无法打开或已经损坏。") from exc
    output: list[ExtractedBlock] = []
    chapter_number = 0
    for item in book.get_items_of_type(ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for unwanted in soup(["script", "style", "nav"]):
            unwanted.decompose()
        paragraphs = [
            _clean_text(node.get_text(" ")) for node in soup.find_all(["p", "li", "blockquote"])
        ]
        paragraphs = [paragraph for paragraph in paragraphs if paragraph]
        if not paragraphs:
            continue
        chapter_number += 1
        title = _chapter_title(soup, f"第 {chapter_number} 节")
        chunk: list[str] = []
        chunk_chars = 0
        chunk_start = 1
        for paragraph_number, paragraph in enumerate(paragraphs, start=1):
            if chunk and chunk_chars + len(paragraph) > 6500:
                output.append(
                    ExtractedBlock(
                        locator={
                            "type": "epub",
                            "chapter": title,
                            "chapter_index": chapter_number,
                            "paragraph_start": chunk_start,
                            "paragraph_end": paragraph_number - 1,
                        },
                        text="\n\n".join(chunk),
                    )
                )
                chunk = []
                chunk_chars = 0
                chunk_start = paragraph_number
            chunk.append(paragraph)
            chunk_chars += len(paragraph)
        if chunk:
            output.append(
                ExtractedBlock(
                    locator={
                        "type": "epub",
                        "chapter": title,
                        "chapter_index": chapter_number,
                        "paragraph_start": chunk_start,
                        "paragraph_end": len(paragraphs),
                    },
                    text="\n\n".join(chunk),
                )
            )
    if not output:
        raise IngestionError("EPUB 中没有可提取的正文段落。")
    return output


def _extract_supplement(title: str, value: str) -> list[ExtractedBlock]:
    paragraphs = [_clean_text(item) for item in re.split(r"\n\s*\n", value)]
    paragraphs = [item for item in paragraphs if item]
    output: list[ExtractedBlock] = []
    chunk: list[str] = []
    chunk_chars = 0
    start = 1
    for index, paragraph in enumerate(paragraphs, start=1):
        if chunk and chunk_chars + len(paragraph) > 6500:
            output.append(
                ExtractedBlock(
                    locator={
                        "type": "text",
                        "section": title,
                        "paragraph_start": start,
                        "paragraph_end": index - 1,
                    },
                    text="\n\n".join(chunk),
                )
            )
            chunk = []
            chunk_chars = 0
            start = index
        chunk.append(paragraph)
        chunk_chars += len(paragraph)
    if chunk:
        output.append(
            ExtractedBlock(
                locator={
                    "type": "text",
                    "section": title,
                    "paragraph_start": start,
                    "paragraph_end": len(paragraphs),
                },
                text="\n\n".join(chunk),
            )
        )
    if not output:
        raise IngestionError("补充资料不能为空。")
    return output


def add_primary_source(
    db: Session,
    settings: Settings,
    project: Project,
    title: str,
    filename: str,
    payload: bytes,
) -> Source:
    if len(payload) > settings.max_primary_bytes:
        raise IngestionError("主书超过 150 MB 限制。")
    existing = db.scalar(
        select(func.count(Source.id)).where(
            Source.project_id == project.id, Source.kind == "primary"
        )
    )
    if existing:
        raise IngestionError("每个项目只能上传一本主书。")
    source_type = _detect_type(filename, payload)
    stored_name = f"{uuid4()}.{source_type}"
    stored_path = settings.data_dir / "uploads" / project.id / stored_name
    stored_path.parent.mkdir(parents=True, exist_ok=True)
    stored_path.write_bytes(payload)
    try:
        blocks = _extract_pdf(payload) if source_type == "pdf" else _extract_epub(stored_path)
        char_count = sum(len(block.text) for block in blocks)
        if char_count > settings.max_primary_chars:
            raise IngestionError("主书提取文本超过 150 万字符限制。")
        source = Source(
            project_id=project.id,
            kind="primary",
            source_type=source_type,
            title=title.strip() or Path(filename).stem,
            original_filename=Path(filename).name,
            stored_path=str(stored_path),
            checksum=_sha256(payload),
            char_count=char_count,
        )
        db.add(source)
        db.flush()
        _persist_blocks(db, project.id, source.id, blocks)
        project.status = ProjectStatus.sources_ready
        db.commit()
        db.refresh(source)
        return source
    except Exception:
        stored_path.unlink(missing_ok=True)
        raise


def add_supplement_source(
    db: Session, settings: Settings, project: Project, title: str, value: str
) -> Source:
    if len(value) > settings.max_supplement_chars:
        raise IngestionError("单份补充资料超过 10 万字符限制。")
    existing = db.scalar(
        select(func.count(Source.id)).where(
            Source.project_id == project.id, Source.kind == "supplement"
        )
    )
    if existing >= settings.max_supplements:
        raise IngestionError("每个项目最多添加五份补充资料。")
    blocks = _extract_supplement(title, value)
    source = Source(
        project_id=project.id,
        kind="supplement",
        source_type="text",
        title=title.strip() or "补充资料",
        checksum=_sha256(value),
        char_count=len(value),
    )
    db.add(source)
    db.flush()
    _persist_blocks(db, project.id, source.id, blocks)
    if any(item.kind == "primary" for item in project.sources):
        project.status = ProjectStatus.sources_ready
    db.commit()
    db.refresh(source)
    return source


def _persist_blocks(
    db: Session, project_id: str, source_id: str, blocks: list[ExtractedBlock]
) -> None:
    for ordinal, block in enumerate(blocks):
        record = SourceBlock(
            source_id=source_id,
            project_id=project_id,
            ordinal=ordinal,
            locator=block.locator,
            text=block.text,
            checksum=_sha256(block.text),
        )
        db.add(record)
        db.flush()
        db.execute(
            text(
                "INSERT INTO source_blocks_fts(block_id, project_id, text) "
                "VALUES (:block_id, :project_id, :body)"
            ),
            {"block_id": record.id, "project_id": project_id, "body": block.text},
        )


def search_blocks(db: Session, project_id: str, query: str, limit: int = 12) -> list[SourceBlock]:
    normalized = _clean_text(query)[:200]
    rows: list[str] = []
    if normalized:
        try:
            result = db.execute(
                text(
                    "SELECT block_id FROM source_blocks_fts "
                    "WHERE source_blocks_fts MATCH :query AND project_id = :project_id LIMIT :limit"
                ),
                {
                    "query": f'"{normalized.replace(chr(34), "")}"',
                    "project_id": project_id,
                    "limit": limit,
                },
            )
            rows = [row[0] for row in result]
        except Exception:
            rows = []
    if rows:
        records = list(db.scalars(select(SourceBlock).where(SourceBlock.id.in_(rows))))
        by_id = {item.id: item for item in records}
        return [by_id[item] for item in rows if item in by_id]
    return list(
        db.scalars(
            select(SourceBlock)
            .where(SourceBlock.project_id == project_id)
            .order_by(SourceBlock.ordinal)
            .limit(limit)
        )
    )


def purge_project_files_and_fts(db: Session, settings: Settings, project_id: str) -> None:
    db.execute(
        text("DELETE FROM source_blocks_fts WHERE project_id = :project_id"),
        {"project_id": project_id},
    )
    db.execute(delete(Project).where(Project.id == project_id))
    db.commit()
    for directory in (
        settings.data_dir / "uploads" / project_id,
        settings.data_dir / "projects" / project_id,
    ):
        if directory.resolve().is_relative_to(settings.data_dir.resolve()):
            shutil.rmtree(directory, ignore_errors=True)
