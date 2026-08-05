from __future__ import annotations

import io

import fitz
from ebooklib import epub


def pdf_bytes(text: str | None = None, pages: int = 1) -> bytes:
    document = fitz.open()
    for _ in range(pages):
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
    return document.tobytes()


def epub_bytes() -> bytes:
    book = epub.EpubBook()
    book.set_identifier("fixture")
    book.set_title("公共领域测试书")
    book.set_language("zh")
    chapter = epub.EpubHtml(title="第一章", file_name="chapter.xhtml", lang="zh")
    chapter.content = "<h1>第一章</h1><p>这是一个关于选择、责任和理解的测试段落。</p><p>第二段提供更多可以核验的文字。</p>"
    book.add_item(chapter)
    book.toc = (epub.Link("chapter.xhtml", "第一章", "chapter"),)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]
    stream = io.BytesIO()
    epub.write_epub(stream, book)
    return stream.getvalue()


def create_project(client) -> str:
    response = client.post("/projects", json={"title": "测试作品", "description": ""})
    assert response.status_code == 201
    return response.json()["id"]


def test_pdf_ingestion_keeps_page_locator(client):
    project_id = create_project(client)
    payload = pdf_bytes("Readable literary source text " * 80)
    response = client.post(
        f"/projects/{project_id}/sources",
        data={"kind": "primary", "title": "测试书"},
        files={"file": ("book.pdf", payload, "application/pdf")},
    )
    assert response.status_code == 201, response.text
    project = client.get(f"/projects/{project_id}").json()
    assert project["status"] == "sources_ready"
    assert project["sources"][0]["source_type"] == "pdf"


def test_epub_ingestion_and_supplement_limit_contract(client):
    project_id = create_project(client)
    response = client.post(
        f"/projects/{project_id}/sources",
        data={"kind": "primary", "title": "测试书"},
        files={"file": ("book.epub", epub_bytes(), "application/epub+zip")},
    )
    assert response.status_code == 201, response.text
    for index in range(5):
        response = client.post(
            f"/projects/{project_id}/sources",
            data={"kind": "supplement", "title": f"笔记{index}", "text_value": "有效补充笔记"},
        )
        assert response.status_code == 201
    response = client.post(
        f"/projects/{project_id}/sources",
        data={"kind": "supplement", "title": "超限", "text_value": "第六份"},
    )
    assert response.status_code == 422


def test_scanned_pdf_is_rejected(client):
    project_id = create_project(client)
    response = client.post(
        f"/projects/{project_id}/sources",
        data={"kind": "primary", "title": "扫描书"},
        files={"file": ("scan.pdf", pdf_bytes(None, pages=3), "application/pdf")},
    )
    assert response.status_code == 422
    assert "OCR" in response.text


def test_file_signature_must_match_extension(client):
    project_id = create_project(client)
    response = client.post(
        f"/projects/{project_id}/sources",
        data={"kind": "primary", "title": "伪装文件"},
        files={"file": ("fake.pdf", b"not a pdf", "application/pdf")},
    )
    assert response.status_code == 422
