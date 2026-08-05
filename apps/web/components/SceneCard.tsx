"use client";

import type {Scene} from "@/lib/types";

interface Props {
  scene: Scene;
  index: number;
  total: number;
  onChange: (scene: Scene) => void;
  onMove: (direction: -1 | 1) => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onRegenerate: (target: "narration" | "visual" | "audio" | "verify") => void;
  onImageUpload: (file: File) => void;
  busy: boolean;
}

const locatorLabel = (locator: Record<string, unknown> | null): string => {
  if (!locator) return "未知位置";
  if (locator.type === "pdf") return `第 ${locator.page_start} 页`;
  if (locator.type === "epub") return `${locator.chapter ?? "章节"} · 段落 ${locator.paragraph_start}`;
  return `${locator.section ?? "补充资料"} · 段落 ${locator.paragraph_start}`;
};

export function SceneCard({scene, index, total, onChange, onMove, onDuplicate, onDelete, onRegenerate, onImageUpload, busy}: Props) {
  const patch = <K extends keyof Scene>(key: K, value: Scene[K]) => onChange({...scene, [key]: value});
  const patchCitation = (citationIndex: number, value: Scene["citations"][number]) =>
    patch("citations", scene.citations.map((citation, index) => index === citationIndex ? value : citation));
  return (
    <article className="scene-card">
      <header className="scene-header">
        <div className="scene-index">{String(index + 1).padStart(2, "0")}</div>
        <input className="scene-title" value={scene.title} onChange={(event) => patch("title", event.target.value)} aria-label="场景标题" />
        <span className={`verification ${scene.verified ? "verified" : "pending"}`}>{scene.verified ? "来源已核验" : "待核验"}</span>
      </header>
      <div className="scene-grid">
        <label className="field wide">
          <span>旁白</span>
          <textarea rows={5} value={scene.narration} onChange={(event) => patch("narration", event.target.value)} />
          <small>{scene.narration.length} 字 · 预计 {Math.round(scene.duration_seconds)} 秒</small>
        </label>
        <label className="field">
          <span>屏幕文字</span>
          <textarea rows={3} value={scene.on_screen_text} onChange={(event) => patch("on_screen_text", event.target.value)} />
        </label>
        <label className="field">
          <span>视觉类型</span>
          <select value={scene.visual_type} onChange={(event) => patch("visual_type", event.target.value as Scene["visual_type"])}>
            <option value="illustration">AI 插画</option>
            <option value="quote_card">原文卡片</option>
            <option value="text_card">主题文字卡</option>
            <option value="relationship_card">人物关系卡</option>
          </select>
        </label>
        <label className="field">
          <span>计划时长（秒）</span>
          <input type="number" min={3} max={45} step={0.5} value={scene.duration_seconds} onChange={(event) => patch("duration_seconds", Number(event.target.value))} />
        </label>
        <label className="field wide">
          <span>视觉提示</span>
          <textarea rows={3} value={scene.visual_prompt} onChange={(event) => patch("visual_prompt", event.target.value)} />
        </label>
      </div>
      <div className="evidence-list">
        {scene.citations.map((citation, citationIndex) => (
          <div className="evidence" key={citation.id || citation.block_id}>
            <select className="evidence-type" value={citation.claim_type} onChange={(event) => patchCitation(citationIndex, {...citation, claim_type: event.target.value as typeof citation.claim_type, verified: false})}>
              <option value="quote">原文</option><option value="fact">事实</option><option value="interpretation">解释</option>
            </select>
            <span>{citation.source_title ? `《${citation.source_title}》` : "来源"} {locatorLabel(citation.locator)}</span>
            <input className="evidence-quote" value={citation.quote} placeholder="支持段落" onChange={(event) => patchCitation(citationIndex, {...citation, quote: event.target.value, verified: false})} />
            <button className="icon-button danger" onClick={() => patch("citations", scene.citations.filter((_, index) => index !== citationIndex))}>×</button>
          </div>
        ))}
      </div>
      <footer className="scene-actions">
        <div>
          <button className="icon-button" disabled={index === 0 || busy} onClick={() => onMove(-1)}>↑</button>
          <button className="icon-button" disabled={index === total - 1 || busy} onClick={() => onMove(1)}>↓</button>
          <button className="text-button" disabled={busy} onClick={onDuplicate}>复制</button>
          <button className="text-button danger" disabled={busy || total <= 1} onClick={onDelete}>删除</button>
        </div>
        <div>
          {!scene.verified ? <button className="text-button" disabled={busy || !scene.id} onClick={() => onRegenerate("verify")}>核验来源</button> : null}
          <button className="text-button" disabled={busy} onClick={() => onRegenerate("narration")}>重写旁白</button>
          <button className="text-button" disabled={busy} onClick={() => onRegenerate("visual")}>重做画面</button>
          <label className={`text-button file-button ${busy || !scene.id ? "disabled" : ""}`}>替换图片<input type="file" accept="image/png,image/jpeg,image/webp" disabled={busy || !scene.id} onChange={(event) => {const file = event.target.files?.[0]; if (file) onImageUpload(file); event.target.value = "";}} /></label>
          {scene.assets.some((asset) => asset.kind === "audio") ? (
            <button className="text-button" disabled={busy} onClick={() => onRegenerate("audio")}>重配语音</button>
          ) : null}
        </div>
      </footer>
    </article>
  );
}
