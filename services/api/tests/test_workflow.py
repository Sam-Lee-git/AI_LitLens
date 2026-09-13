from __future__ import annotations

import io

from PIL import Image
from test_ingestion import create_project, pdf_bytes

from app.worker import run_once


def ready_project(client) -> str:
    project_id = create_project(client)
    payload = pdf_bytes("A source paragraph about responsibility and moral choice. " * 120)
    response = client.post(
        f"/projects/{project_id}/sources",
        data={"kind": "primary", "title": "测试书"},
        files={"file": ("book.pdf", payload, "application/pdf")},
    )
    assert response.status_code == 201
    return project_id


def test_title_only_project_builds_model_knowledge_and_angles(client):
    response = client.post(
        "/projects",
        json={
            "title": "罪与罚",
            "description": "重点讨论人物为什么为自己的选择辩护",
            "auto_analyze": True,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "analyzing"
    project_id = response.json()["id"]
    assert run_once() is True

    project = client.get(f"/projects/{project_id}").json()
    assert project["status"] == "angles_ready"
    assert len(project["angles"]) == 5
    assert len(project["sources"]) == 1
    assert project["sources"][0]["kind"] == "model"
    assert project["sources"][0]["source_type"] == "model_knowledge"

    response = client.put(
        f"/projects/{project_id}/angle", json={"angle_id": project["angles"][0]["id"]}
    )
    assert response.status_code == 202
    assert run_once() is True
    board = client.get(f"/projects/{project_id}/storyboard").json()
    assert 12 <= len(board["scenes"]) <= 18
    assert all(scene["verified"] for scene in board["scenes"])
    assert all(
        citation["claim_type"] == "interpretation" and citation["quote"] == ""
        for scene in board["scenes"]
        for citation in scene["citations"]
    )
    assert all(
        citation["locator"]["type"] == "model_knowledge"
        for scene in board["scenes"]
        for citation in scene["citations"]
    )


def test_uploaded_original_replaces_model_knowledge_as_storyboard_evidence(client):
    response = client.post(
        "/projects", json={"title": "测试名著", "description": "", "auto_analyze": True}
    )
    project_id = response.json()["id"]
    assert run_once() is True
    payload = pdf_bytes("A verifiable original paragraph about choice and responsibility. " * 100)
    response = client.post(
        f"/projects/{project_id}/sources",
        data={"kind": "primary", "title": "测试名著原文"},
        files={"file": ("original.pdf", payload, "application/pdf")},
    )
    assert response.status_code == 201, response.text
    client.post(f"/projects/{project_id}/analyze").raise_for_status()
    assert run_once() is True
    project = client.get(f"/projects/{project_id}").json()
    client.put(
        f"/projects/{project_id}/angle", json={"angle_id": project["angles"][0]["id"]}
    ).raise_for_status()
    assert run_once() is True
    board = client.get(f"/projects/{project_id}/storyboard").json()
    assert all(
        citation["locator"]["type"] == "pdf"
        for scene in board["scenes"]
        for citation in scene["citations"]
    )


def test_mock_analysis_to_editable_storyboard(client):
    project_id = ready_project(client)
    first = client.post(f"/projects/{project_id}/analyze")
    second = client.post(f"/projects/{project_id}/analyze")
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert run_once() is True
    project = client.get(f"/projects/{project_id}").json()
    assert project["status"] == "angles_ready"
    assert len(project["angles"]) == 5

    response = client.put(
        f"/projects/{project_id}/angle", json={"angle_id": project["angles"][0]["id"]}
    )
    assert response.status_code == 202
    assert run_once() is True
    board = client.get(f"/projects/{project_id}/storyboard").json()
    assert 12 <= len(board["scenes"]) <= 18
    assert all(scene["citations"] for scene in board["scenes"])
    assert board["estimated_cost_usd"] <= 5

    changed = board.copy()
    changed["scenes"] = [dict(scene) for scene in board["scenes"]]
    changed["scenes"][0]["narration"] += " 用户新增的解释。"
    saved = client.put(f"/projects/{project_id}/storyboard", json=changed)
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == board["revision"] + 1
    assert saved.json()["scenes"][0]["verified"] is False
    review = client.post(
        f"/projects/{project_id}/scenes/{saved.json()['scenes'][0]['id']}/regenerate",
        json={"target": "verify", "instruction": ""},
    )
    assert review.status_code == 200
    assert review.json()["verified"] is True


def test_optimistic_revision_and_citation_gate(client):
    project_id = ready_project(client)
    client.post(f"/projects/{project_id}/analyze")
    run_once()
    project = client.get(f"/projects/{project_id}").json()
    client.put(f"/projects/{project_id}/angle", json={"angle_id": project["angles"][0]["id"]})
    run_once()
    board = client.get(f"/projects/{project_id}/storyboard").json()
    stale = {**board, "revision": board["revision"] - 1}
    assert client.put(f"/projects/{project_id}/storyboard", json=stale).status_code == 409
    board["scenes"][0]["citations"] = []
    saved = client.put(f"/projects/{project_id}/storyboard", json=board)
    assert saved.status_code == 200
    approval = client.post(
        f"/projects/{project_id}/storyboard/approve", json={"override_budget": False}
    )
    assert approval.status_code == 422


def test_scene_image_replacement_and_voice_setting(client):
    project_id = ready_project(client)
    client.post(f"/projects/{project_id}/analyze")
    run_once()
    project = client.get(f"/projects/{project_id}").json()
    client.put(f"/projects/{project_id}/angle", json={"angle_id": project["angles"][0]["id"]})
    run_once()
    board = client.get(f"/projects/{project_id}/storyboard").json()
    scene_id = board["scenes"][0]["id"]
    assert (
        client.post(
            f"/projects/{project_id}/scenes/{scene_id}/image",
            files={"file": ("fake.png", b"not an image", "image/png")},
        ).status_code
        == 422
    )
    image = Image.new("RGB", (320, 480), "#31283a")
    stream = io.BytesIO()
    image.save(stream, "PNG")
    uploaded = client.post(
        f"/projects/{project_id}/scenes/{scene_id}/image",
        files={"file": ("replacement.png", stream.getvalue(), "image/png")},
    )
    assert uploaded.status_code == 201, uploaded.text
    board = client.get(f"/projects/{project_id}/storyboard").json()
    assert any(asset["kind"] == "image" for asset in board["scenes"][0]["assets"])
    board["speech_voice"] = "nova"
    saved = client.put(f"/projects/{project_id}/storyboard", json=board)
    assert saved.status_code == 200, saved.text
    assert saved.json()["speech_voice"] == "nova"
