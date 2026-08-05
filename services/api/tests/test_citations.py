from app.models import Citation, SourceBlock
from app.services.citations import verify_citation


def test_exact_quote_verifies():
    block = SourceBlock(
        source_id="s",
        project_id="p",
        ordinal=0,
        locator={},
        text="真正的改变来自重新看见他人。",
        checksum="x",
    )
    citation = Citation(scene_id="scene", block_id="b", claim_type="quote", quote="重新看见他人")
    assert verify_citation(citation, block) == (True, 1.0)


def test_interpretation_requires_supporting_text():
    block = SourceBlock(source_id="s", project_id="p", ordinal=0, locator={}, text="", checksum="x")
    citation = Citation(scene_id="scene", block_id="b", claim_type="interpretation", quote="")
    assert verify_citation(citation, block)[0] is False
