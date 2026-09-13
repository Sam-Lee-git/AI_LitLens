from __future__ import annotations

import base64
import json
import re
import subprocess
import wave
from abc import ABC, abstractmethod
from pathlib import Path

from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field

from ..config import Settings


class BookKnowledgeBlockOutput(BaseModel):
    heading: str
    text: str


class BookKnowledgeOutput(BaseModel):
    canonical_title: str
    author: str
    identification_note: str
    blocks: list[BookKnowledgeBlockOutput] = Field(min_length=8, max_length=16)


class AngleOutput(BaseModel):
    title: str
    hook: str
    thesis: str
    audience_value: str
    evidence_block_ids: list[str] = Field(min_length=1)


class AngleOutputBatch(BaseModel):
    angles: list[AngleOutput] = Field(min_length=5, max_length=5)


class CitationOutput(BaseModel):
    block_id: str
    claim_type: str
    quote: str = ""


class SceneOutput(BaseModel):
    title: str
    narration: str
    on_screen_text: str
    visual_type: str
    visual_prompt: str
    duration_seconds: float
    citations: list[CitationOutput] = Field(min_length=1)


class StoryboardOutput(BaseModel):
    scenes: list[SceneOutput] = Field(min_length=12, max_length=18)


class TextProvider(ABC):
    @abstractmethod
    def generate_book_knowledge(self, title: str, focus: str) -> dict: ...

    @abstractmethod
    def build_book_map(self, title: str, blocks: list[dict]) -> dict: ...

    @abstractmethod
    def generate_angles(self, title: str, book_map: dict, blocks: list[dict]) -> list[dict]: ...

    @abstractmethod
    def generate_storyboard(
        self, title: str, angle: dict, style: str, blocks: list[dict]
    ) -> list[dict]: ...

    def generate_publishing_copy(self, title: str, angle: str) -> str:
        return (
            f"# {title}\n\n{angle}\n\n"
            "这是一段由 AI 辅助制作的文学解读视听内容。内容依据与出处说明见随附清单。\n\n"
            "## 推荐标签\n\n#文学 #读书 #经典名著 #深度解读\n"
        )

    @abstractmethod
    def regenerate_scene(self, scene: dict, instruction: str, evidence: list[dict]) -> dict: ...


class ImageProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, output: Path, title: str) -> None: ...


class SpeechProvider(ABC):
    @abstractmethod
    def synthesize(self, narration: str, output: Path, voice: str | None = None) -> None: ...


def _excerpt(text: str, limit: int = 120) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    return clean[:limit] + ("……" if len(clean) > limit else "")


class MockTextProvider(TextProvider):
    def generate_book_knowledge(self, title: str, focus: str) -> dict:
        topics = [
            ("作品定位", "作品所处的文学传统、时代语境与最常被讨论的价值问题。"),
            ("故事结构", "故事如何设置冲突、推进选择，并让人物承担选择带来的后果。"),
            ("核心人物", "主要人物的欲望、恐惧、盲点与变化构成了解读的基本坐标。"),
            ("人物关系", "关键关系既推动情节，也暴露权力、责任、爱与误解之间的张力。"),
            ("核心冲突", "人物的外部处境与内在信念相互挤压，形成作品持续生效的矛盾。"),
            ("主题线索", "作品可以从自由、责任、身份、欲望、伦理和救赎等维度继续追问。"),
            ("叙事方法", "视角、节奏、反复出现的意象与场景安排共同塑造读者判断。"),
            ("关键转折", "决定性的选择会重排人物关系，也让作品的核心命题变得可见。"),
            ("当代价值", "经典的意义不在提供标准答案，而在帮助今天的读者重新描述困境。"),
            ("解读边界", "这份底稿来自模型作品知识，不包含原文逐字引语或可核验页码。"),
        ]
        focus_note = f" 用户希望重点关注：{focus.strip()}" if focus.strip() else ""
        return {
            "canonical_title": title,
            "author": "演示模式未核定作者",
            "identification_note": "演示模式按用户输入的作品名建立知识底稿。",
            "blocks": [
                {
                    "heading": heading,
                    "text": f"《{title}》的{heading}知识底稿：{body}{focus_note}",
                }
                for heading, body in topics
            ],
        }

    def build_book_map(self, title: str, blocks: list[dict]) -> dict:
        chapters = [
            {
                "block_id": block["id"],
                "locator": block["locator"],
                "summary": _excerpt(block["text"], 180),
            }
            for block in blocks[:40]
        ]
        return {"title": title, "chapters": chapters, "mode": "mock"}

    def generate_angles(self, title: str, book_map: dict, blocks: list[dict]) -> list[dict]:
        templates = [
            ("人物真正害怕的是什么？", "恐惧往往不来自惩罚，而来自自我解释的崩塌。"),
            ("一个理论如何改变一个人的命运？", "当观念凌驾于具体的人，悲剧就已经开始。"),
            ("为什么这本书仍然属于今天？", "经典最尖锐的部分，往往正发生在现代生活里。"),
            ("作者如何把思想写成审判？", "故事不是答案，而是一场持续逼近人物的审问。"),
            ("救赎究竟意味着什么？", "真正的改变不是被原谅，而是重新看见他人。"),
        ]
        knowledge_only = bool(blocks) and all(
            block.get("source_type") == "model_knowledge" for block in blocks
        )
        evidence = [block["id"] for block in blocks[:10]] or [""]
        return [
            {
                "title": f"{title}：{angle_title}",
                "hook": hook,
                "thesis": (
                    f"从作品知识出发，解释《{title}》如何呈现这一核心矛盾。"
                    if knowledge_only
                    else f"从文本细节出发，解释《{title}》如何呈现这一核心矛盾。"
                ),
                "audience_value": "帮助没有读完原著的观众抓住一个清楚、可讨论的思想入口。",
                "evidence_block_ids": [evidence[index % len(evidence)]],
            }
            for index, (angle_title, hook) in enumerate(templates)
        ]

    def generate_storyboard(
        self, title: str, angle: dict, style: str, blocks: list[dict]
    ) -> list[dict]:
        usable = blocks or [{"id": "", "text": "", "locator": {}}]
        scenes: list[dict] = []
        for index in range(12):
            block = usable[index % len(usable)]
            snippet = _excerpt(block["text"], 50)
            model_knowledge = block.get("source_type") == "model_knowledge"
            if index == 0:
                narration = (
                    f"为什么《{title}》直到今天仍让人不安？真正值得追问的，是{angle['thesis']}"
                )
                screen = angle["hook"]
            elif index == 11:
                narration = (
                    f"回到最初的问题，《{title}》留下的不是标准答案，而是一种重新审视自己的方法。"
                )
                screen = "经典不是答案，而是一面镜子"
            else:
                prefix = "作品知识底稿提示" if model_knowledge else "文本在这里写道"
                narration = f"{prefix}：{snippet}。这段细节让我们看到，{angle['thesis']}"
                screen = snippet[:32]
            scenes.append(
                {
                    "title": f"场景 {index + 1}",
                    "narration": narration,
                    "on_screen_text": screen,
                    "visual_type": "illustration"
                    if index in {0, 1, 3, 5, 7, 9, 10, 11}
                    else ("text_card" if model_knowledge else "quote_card"),
                    "visual_prompt": (
                        f"{style}，文学油画插图，电影感光影，与《{title}》主题相关；"
                        "不要生成文字、标志或现代品牌。"
                    ),
                    "duration_seconds": max(10.0, min(22.0, len(narration) / 4.0)),
                    "citations": [
                        {
                            "block_id": block["id"],
                            "claim_type": (
                                "interpretation" if model_knowledge or index in {0, 11} else "quote"
                            ),
                            "quote": "" if model_knowledge else snippet.removesuffix("……")[:80],
                        }
                    ],
                }
            )
        return scenes

    def regenerate_scene(self, scene: dict, instruction: str, evidence: list[dict]) -> dict:
        updated = dict(scene)
        suffix = instruction.strip() or "让表达更清楚、更有节奏"
        updated["narration"] = f"{scene['narration'].rstrip('。')}。重新聚焦：{suffix}。"
        updated["on_screen_text"] = scene.get("on_screen_text") or suffix[:24]
        return updated


class OpenAITextProvider(TextProvider):
    def __init__(self, settings: Settings):
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.text_model

    def _parse(self, instructions: str, payload: dict, schema: type[BaseModel]) -> BaseModel:
        response = self.client.responses.parse(
            model=self.model,
            reasoning={"effort": "medium"},
            store=False,
            instructions=instructions,
            input=json.dumps(payload, ensure_ascii=False),
            text_format=schema,
        )
        if response.output_parsed is None:
            raise RuntimeError("模型没有返回可解析的结构化结果。")
        return response.output_parsed

    def generate_book_knowledge(self, title: str, focus: str) -> dict:
        result = self._parse(
            "你是严谨的中文文学研究编辑。根据作品名识别最常见的同名文学作品，并建立作品知识底稿。"
            "底稿覆盖作者与时代、情节结构、核心人物、人物关系、主题、关键转折、叙事方法和当代价值。"
            "只写你有把握的通识性信息；作品名有歧义时在 identification_note 说明你的识别。"
            "不要生成原文逐字引语、页码或伪造出处。每个知识块应独立、具体，适合支持后续解释性论断。",
            {"title": title, "focus": focus},
            BookKnowledgeOutput,
        )
        return result.model_dump()

    def build_book_map(self, title: str, blocks: list[dict]) -> dict:
        summaries: list[dict] = []
        for block in blocks:
            summaries.append(
                {
                    "block_id": block["id"],
                    "locator": block["locator"],
                    "excerpt": _excerpt(block["text"], 500),
                }
            )
        return {"title": title, "evidence_catalog": summaries[:200], "mode": "openai"}

    def generate_angles(self, title: str, book_map: dict, blocks: list[dict]) -> list[dict]:
        result = self._parse(
            "你是严谨的中文文学编辑。只能依据 evidence_catalog，生成恰好五个差异明显的解读角度。"
            "每个角度必须引用至少一个真实 block_id，不得虚构原文或情节。",
            {"title": title, "book_map": book_map},
            AngleOutputBatch,
        )
        return [item.model_dump() for item in result.angles]  # type: ignore[attr-defined]

    def generate_storyboard(
        self, title: str, angle: dict, style: str, blocks: list[dict]
    ) -> list[dict]:
        knowledge_only = bool(blocks) and all(
            block.get("source_type") == "model_knowledge" for block in blocks
        )
        evidence = [
            {
                "id": block["id"],
                "source_type": block.get("source_type", "text"),
                "locator": block["locator"],
                "text": _excerpt(block["text"], 900),
            }
            for block in blocks[:80]
        ]
        source_rule = (
            "当前 evidence 是模型作品知识底稿，不是原文。所有 citation 的 claim_type 必须为 "
            "interpretation，quote 必须为空；旁白不得声称逐字引用原著，视觉类型不得使用 quote_card。"
            if knowledge_only
            else "直接引文必须逐字来自 evidence；解释性判断使用 interpretation。"
        )
        result = self._parse(
            "生成12至18个简体中文场景，总旁白900至1300字，适合3至5分钟竖屏文学解读。"
            "每个场景必须含至少一个 evidence 中真实存在的 block_id。"
            f"{source_rule}视觉类型仅允许 illustration、quote_card、text_card、relationship_card。",
            {"title": title, "angle": angle, "style": style, "evidence": evidence},
            StoryboardOutput,
        )
        return [item.model_dump() for item in result.scenes]  # type: ignore[attr-defined]

    def regenerate_scene(self, scene: dict, instruction: str, evidence: list[dict]) -> dict:
        result = self._parse(
            "只重写一个中文文学解读场景。保持原论点和真实 block_id，直接引文必须逐字来自 evidence。"
            "视觉类型仅允许 illustration、quote_card、text_card、relationship_card。",
            {"scene": scene, "instruction": instruction, "evidence": evidence},
            SceneOutput,
        )
        return result.model_dump()


class MockImageProvider(ImageProvider):
    def generate(self, prompt: str, output: Path, title: str) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        image = Image.new("RGB", (1024, 1536), (27, 25, 35))
        draw = ImageDraw.Draw(image)
        for y in range(1536):
            ratio = y / 1536
            draw.line(
                (0, y, 1024, y),
                fill=(int(27 + 32 * ratio), int(25 + 18 * ratio), int(35 + 45 * ratio)),
            )
        small = self._font(26)
        draw.rounded_rectangle(
            (90, 450, 934, 1080), radius=38, fill=(16, 15, 24), outline=(207, 169, 98), width=4
        )
        draw.ellipse((260, 565, 765, 990), outline=(207, 169, 98), width=3)
        draw.arc((180, 500, 850, 1060), 198, 342, fill=(118, 88, 130), width=9)
        draw.line((140, 790, 884, 620), fill=(102, 77, 111), width=3)
        draw.text((140, 1010), "DEMO VISUAL", font=small, fill=(207, 169, 98))
        image.save(output, "PNG")

    @staticmethod
    def _font(size: int):
        for candidate in (
            Path("C:/Windows/Fonts/msyh.ttc"),
            Path("C:/Windows/Fonts/msyhbd.ttc"),
            Path("C:/Windows/Fonts/simhei.ttf"),
        ):
            if candidate.exists():
                return ImageFont.truetype(candidate, size=size)
        return ImageFont.load_default(size=size)


class OpenAIImageProvider(ImageProvider):
    def __init__(self, settings: Settings):
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.image_model

    def generate(self, prompt: str, output: Path, title: str) -> None:
        result = self.client.images.generate(
            model=self.model,
            prompt=prompt,
            size="1024x1536",
            quality="medium",
        )
        if not result.data or not result.data[0].b64_json:
            raise RuntimeError("图片接口没有返回图像数据。")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(base64.b64decode(result.data[0].b64_json))


class MockSpeechProvider(SpeechProvider):
    def synthesize(self, narration: str, output: Path, voice: str | None = None) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        duration = max(3.0, len(narration) / 4.2)
        sample_rate = 24_000
        frames = int(duration * sample_rate)
        with wave.open(str(output), "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(sample_rate)
            target.writeframes(b"\x00\x00" * frames)


class OpenAISpeechProvider(SpeechProvider):
    def __init__(self, settings: Settings):
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.speech_model
        self.voice = settings.speech_voice

    def synthesize(self, narration: str, output: Path, voice: str | None = None) -> None:
        response = self.client.audio.speech.create(
            model=self.model,
            voice=voice or self.voice,
            input=narration,
            response_format="mp3",
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(response.read())


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def make_providers(settings: Settings) -> tuple[TextProvider, ImageProvider, SpeechProvider]:
    if settings.resolved_provider == "openai":
        return (
            OpenAITextProvider(settings),
            OpenAIImageProvider(settings),
            OpenAISpeechProvider(settings),
        )
    return MockTextProvider(), MockImageProvider(), MockSpeechProvider()
