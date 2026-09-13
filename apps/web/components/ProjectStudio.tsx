"use client";

import {FormEvent, useCallback, useEffect, useMemo, useState} from "react";
import {ApiError, API_URL, api, humanError, projectApi} from "@/lib/api";
import type {ExportItem, ProgressEvent, Project, Scene, Storyboard} from "@/lib/types";
import {SceneCard} from "./SceneCard";
import {VideoPreview} from "./VideoPreview";

const STATUS: Record<Project["status"], string> = {
  draft: "等待开始",
  sources_ready: "可重新分析",
  analyzing: "分析中",
  angles_ready: "选择角度",
  storyboard_review: "审核故事板",
  approved: "已批准",
  generating_media: "生成媒体",
  rendering: "渲染视频",
  completed: "已完成",
  failed: "需要处理",
};

const ACTIVE = new Set<Project["status"]>(["analyzing", "approved", "generating_media", "rendering"]);

export function ProjectStudio() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [board, setBoard] = useState<Storyboard | null>(null);
  const [exports, setExports] = useState<ExportItem[]>([]);
  const [provider, setProvider] = useState("unknown");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [progress, setProgress] = useState<ProgressEvent | null>(null);

  const loadProject = useCallback(async (id: string) => {
    const next = await projectApi.get(id);
    setProject(next);
    if (["storyboard_review", "approved", "generating_media", "rendering", "completed"].includes(next.status)) {
      const nextBoard = await projectApi.storyboard(id).catch(() => null);
      setBoard(nextBoard);
    } else {
      setBoard(null);
    }
    if (next.status === "completed") setExports(await projectApi.exports(id));
    return next;
  }, []);

  const refreshList = useCallback(async () => {
    const next = await projectApi.list();
    setProjects(next);
    return next;
  }, []);

  useEffect(() => {
    Promise.all([refreshList(), api<{provider: string}>("/health")])
      .then(([items, health]) => {
        setProvider(health.provider);
        if (items[0]) setActiveId((current) => current ?? items[0].id);
      })
      .catch((reason) => setError(humanError(reason)));
  }, [refreshList]);

  useEffect(() => {
    if (!activeId) {
      setProject(null);
      return;
    }
    loadProject(activeId).catch((reason) => setError(humanError(reason)));
  }, [activeId, loadProject]);

  useEffect(() => {
    if (!activeId) return;
    const source = new EventSource(`${API_URL}/projects/${activeId}/events`);
    source.addEventListener("progress", (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as ProgressEvent;
      setProgress(payload);
      if (["analysis_complete", "storyboard_complete", "storyboard_saved", "complete", "failed"].includes(payload.kind)) {
        Promise.all([loadProject(activeId), refreshList()]).catch(() => undefined);
      }
    });
    return () => source.close();
  }, [activeId, loadProject, refreshList]);

  const act = async (operation: () => Promise<unknown>, success?: string) => {
    setBusy(true);
    setError("");
    try {
      await operation();
      if (success) setNotice(success);
      if (activeId) await loadProject(activeId);
      await refreshList();
    } catch (reason) {
      setError(humanError(reason));
      throw reason;
    } finally {
      setBusy(false);
    }
  };

  const createProject = async (title: string, description: string) => {
    let created: Project | null = null;
    await act(async () => {
      created = await projectApi.create(title, description);
    }, "大模型已经开始理解这部作品");
    if (created) setActiveId((created as Project).id);
  };

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">墨</div>
          <div><strong>墨镜</strong><span>AI 文学解读 Agent</span></div>
        </div>
        <NewProjectForm onCreate={createProject} busy={busy} />
        <nav className="project-list" aria-label="项目列表">
          <div className="list-label">内容项目</div>
          {projects.map((item) => (
            <button key={item.id} className={`project-item ${item.id === activeId ? "active" : ""}`} onClick={() => setActiveId(item.id)}>
              <span className="project-title">{item.title}</span>
              <span className={`status-dot ${item.status}`} />
              <small>{STATUS[item.status]}</small>
            </button>
          ))}
          {!projects.length ? <p className="empty-hint">先创建第一个文学解读项目。</p> : null}
        </nav>
        <div className="provider-badge">
          <span className={provider === "openai" ? "live-dot" : "demo-dot"} />
          {provider === "openai" ? "OpenAI 实时模式" : "无费用演示模式"}
        </div>
      </aside>

      <section className="workspace">
        {error ? <div className="toast error" onClick={() => setError("")}>{error}</div> : null}
        {notice ? <div className="toast notice" onClick={() => setNotice("")}>{notice}</div> : null}
        {!project ? <Welcome onCreate={createProject} busy={busy} /> : (
          <>
            <ProjectHeader
              project={project}
              busy={busy}
              onDelete={() => {
                if (!window.confirm(`删除《${project.title}》及全部本地文件？此操作不可撤销。`)) return;
                act(() => projectApi.remove(project.id)).then(() => {
                  setActiveId(null);
                  setProject(null);
                  setBoard(null);
                }).catch(() => undefined);
              }}
            />
            {ACTIVE.has(project.status) ? <ProgressPanel project={project} event={progress} /> : null}
            {project.status === "angles_ready" ? (
              <AnglePicker project={project} busy={busy} onChoose={(angleId) => act(() => projectApi.chooseAngle(project.id, angleId), "正在生成故事板")} />
            ) : null}
            {["draft", "sources_ready", "angles_ready"].includes(project.status) ? (
              <SourcePanel
                project={project}
                busy={busy}
                onUpload={(form) => act(() => api(`/projects/${project.id}/sources`, {method: "POST", body: form}), "资料已加入项目")}
                onAnalyze={() => act(() => projectApi.analyze(project.id), "分析任务已经开始")}
              />
            ) : null}
            {board && ["storyboard_review", "completed"].includes(project.status) ? (
              <StoryboardEditor
                project={project}
                initial={board}
                busy={busy}
                onSave={async (next) => {
                  await act(async () => setBoard(await projectApi.saveStoryboard(project.id, next)), "故事板已保存；改动场景需要重新核验");
                }}
                onApprove={async () => {
                  try {
                    await act(() => projectApi.approve(project.id), "媒体生成任务已经开始");
                  } catch (reason) {
                    if (reason instanceof ApiError && reason.status === 409 && window.confirm("预计费用超过默认预算 US$5。是否明确覆盖预算并继续？")) {
                      await act(() => projectApi.approve(project.id, true), "已覆盖预算，媒体生成任务已经开始");
                    }
                  }
                }}
                onRegenerate={async (sceneId, target) => {
                  const instruction = target === "narration" ? window.prompt("希望如何重写这个场景？", "更凝练、更有叙事张力") ?? "" : "";
                  const message = target === "verify" ? "来源核验已完成" : "场景已更新，请重新审核并保存";
                  await act(() => projectApi.regenerate(project.id, sceneId, target, instruction), message);
                  setBoard(await projectApi.storyboard(project.id));
                }}
                onImageUpload={async (sceneId, file) => {
                  await act(() => projectApi.uploadImage(project.id, sceneId, file), "场景图片已替换");
                  setBoard(await projectApi.storyboard(project.id));
                }}
                onMusicUpload={async (file) => {
                  await act(() => projectApi.uploadMusic(project.id, file), "背景音乐已上传并记录权利确认");
                }}
              />
            ) : null}
            {project.status === "completed" && board ? (
              <CompletedPanel project={project} board={board} exports={exports} />
            ) : null}
          </>
        )}
      </section>
    </main>
  );
}

function NewProjectForm({onCreate, busy}: {onCreate: (title: string, description: string) => Promise<void>; busy: boolean}) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!title.trim()) return;
    await onCreate(title, description);
    setTitle(""); setDescription(""); setOpen(false);
  };
  return open ? (
    <form className="new-project-form" onSubmit={submit}>
      <input autoFocus placeholder="输入名著名称" value={title} onChange={(event) => setTitle(event.target.value)} />
      <textarea placeholder="想重点关注什么（可选）" value={description} onChange={(event) => setDescription(event.target.value)} />
      <div><button className="primary small" disabled={busy}>{busy ? "正在启动…" : "开始解读"}</button><button type="button" className="ghost small" onClick={() => setOpen(false)}>取消</button></div>
    </form>
  ) : <button className="new-project" onClick={() => setOpen(true)}>＋ 输入一本名著</button>;
}

function Welcome({onCreate, busy}: {onCreate: (title: string, description: string) => Promise<void>; busy: boolean}) {
  const [title, setTitle] = useState("");
  const [focus, setFocus] = useState("");
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!title.trim()) return;
    await onCreate(title, focus);
  };
  return (
    <div className="welcome">
      <div className="eyebrow">FROM TITLE TO STORY</div>
      <h1>说出一本名著，<br />剩下的交给 AI。</h1>
      <p>输入作品名，大模型会理解人物、情节与主题，提出五个值得讲的角度，再生成可编辑的竖屏内容。</p>
      <form className="title-launch" onSubmit={submit}>
        <label>
          <span>名著名称</span>
          <input autoFocus placeholder="例如：红楼梦、罪与罚、百年孤独" value={title} onChange={(event) => setTitle(event.target.value)} />
        </label>
        <label>
          <span>特别想讲什么？（可选）</span>
          <input placeholder="例如：人物命运、爱情观、为什么今天还值得读" value={focus} onChange={(event) => setFocus(event.target.value)} />
        </label>
        <button className="primary launch-button" disabled={busy || !title.trim()}>{busy ? "AI 正在启动…" : "让 AI 开始解读 →"}</button>
        <small>无需先找电子书。需要逐页出处时，可在之后补充 PDF 或 EPUB。</small>
      </form>
      <div className="flow"><span>01 输入书名</span><i /><span>02 选择角度</span><i /><span>03 审核场景</span><i /><span>04 生成成品</span></div>
    </div>
  );
}

function ProjectHeader({project, busy, onDelete}: {project: Project; busy: boolean; onDelete: () => void}) {
  return (
    <header className="project-header">
      <div><div className="eyebrow">LITERARY PROJECT</div><h1>《{project.title}》</h1><p>{project.description || "从作品知识中找到一个值得讲的观点。"}</p></div>
      <div className="header-actions"><span className={`status-pill ${project.status}`}>{STATUS[project.status]}</span><button className="ghost danger" disabled={busy} onClick={onDelete}>删除项目</button></div>
    </header>
  );
}

function ProgressPanel({project, event}: {project: Project; event: ProgressEvent | null}) {
  const pct = Math.round((event?.progress ?? (project.status === "rendering" ? .86 : .2)) * 100);
  return (
    <section className="progress-panel">
      <div className="spinner" /><div className="progress-copy"><strong>{event?.message ?? STATUS[project.status]}</strong><span>任务会保存每个成功步骤，可以安全恢复。</span><div className="progress-track"><i style={{width: `${pct}%`}} /></div></div><b>{pct}%</b>
    </section>
  );
}

function SourcePanel({project, busy, onUpload, onAnalyze}: {project: Project; busy: boolean; onUpload: (form: FormData) => Promise<unknown>; onAnalyze: () => Promise<unknown>}) {
  const [tab, setTab] = useState<"primary" | "supplement">("primary");
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const hasPrimary = project.sources.some((source) => source.kind === "primary");
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const form = new FormData(); form.set("kind", tab); form.set("title", title || file?.name.replace(/\.[^.]+$/, "") || "补充资料");
    if (tab === "primary" && file) form.set("file", file); else form.set("text_value", text);
    await onUpload(form); setTitle(""); setText(""); setFile(null);
  };
  return (
    <section className="panel sources-panel optional-panel">
      <div className="section-heading"><div><span className="step-number optional">+</span><div><h2>出处增强 <small>可选</small></h2><p>AI 已可根据书名工作；上传原著后，可重新分析并获得页码或章节定位。</p></div></div>{project.status === "draft" ? <button className="primary" disabled={busy} onClick={onAnalyze}>直接让 AI 解读 →</button> : project.status === "sources_ready" ? <button className="primary" disabled={busy} onClick={onAnalyze}>用新增资料重新分析 →</button> : null}</div>
      {project.sources.length ? <div className="source-list">{project.sources.map((source) => {
        const isModel = source.kind === "model";
        const icon = isModel ? "AI" : source.source_type === "pdf" ? "PDF" : source.source_type === "epub" ? "EPUB" : "TXT";
        const detail = isModel ? "模型作品知识 · 非原文出处" : `${source.kind === "primary" ? "原著" : "补充资料"} · ${source.char_count.toLocaleString()} 字符`;
        return <div className={`source-chip ${isModel ? "model-source" : ""}`} key={source.id}><span className="file-icon">{icon}</span><div><strong>{source.title}</strong><small>{detail}</small></div></div>;
      })}</div> : null}
      {!ACTIVE.has(project.status) && project.status !== "completed" && (!hasPrimary || project.sources.filter((source) => source.kind === "supplement").length < 5) ? (
        <form className="source-form" onSubmit={submit}>
          <div className="tabs"><button type="button" className={tab === "primary" ? "active" : ""} disabled={hasPrimary} onClick={() => setTab("primary")}>原著文件（可选）</button><button type="button" className={tab === "supplement" ? "active" : ""} onClick={() => setTab("supplement")}>补充笔记（可选）</button></div>
          <input placeholder="资料标题" value={title} onChange={(event) => setTitle(event.target.value)} />
          {tab === "primary" ? <label className="drop-zone"><input type="file" accept=".pdf,.epub" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /><strong>{file ? file.name : "选择 PDF 或 EPUB"}</strong><span>文字型文件，最大 150 MB；扫描件暂不支持</span></label> : <textarea rows={6} placeholder="粘贴读书笔记、研究文章或自己的想法……" value={text} onChange={(event) => setText(event.target.value)} />}
          <button className="secondary" disabled={busy || (tab === "primary" ? !file : !text.trim())}>添加资料</button>
        </form>
      ) : null}
    </section>
  );
}

function AnglePicker({project, busy, onChoose}: {project: Project; busy: boolean; onChoose: (id: string) => Promise<unknown>}) {
  const modelKnowledgeOnly = project.sources.length > 0 && project.sources.every((source) => source.kind === "model");
  return (
    <section className="panel">
      <div className="section-heading"><div><span className="step-number">02</span><div><h2>选择一个值得讲的角度</h2><p>{modelKnowledgeOnly ? "五个方向来自 AI 作品知识；选择后会生成完整场景。" : "五个方向都来自当前资料；选择后会生成完整场景。"}</p></div></div></div>
      <div className="angle-grid">{project.angles.map((angle) => <button className="angle-card" key={angle.id} disabled={busy} onClick={() => onChoose(angle.id)}><span>方向 {angle.ordinal + 1}</span><h3>{angle.title}</h3><blockquote>{angle.hook}</blockquote><p>{angle.thesis}</p><footer>{angle.evidence_block_ids.length} 条{modelKnowledgeOnly ? "知识依据" : "核心证据"} <b>选择 →</b></footer></button>)}</div>
    </section>
  );
}

function StoryboardEditor({project, initial, busy, onSave, onApprove, onRegenerate, onImageUpload, onMusicUpload}: {project: Project; initial: Storyboard; busy: boolean; onSave: (board: Storyboard) => Promise<void>; onApprove: () => Promise<void>; onRegenerate: (sceneId: string, target: "narration" | "visual" | "audio" | "verify") => Promise<void>; onImageUpload: (sceneId: string, file: File) => Promise<void>; onMusicUpload: (file: File) => Promise<void>}) {
  const [draft, setDraft] = useState(initial);
  const [music, setMusic] = useState<File | null>(null);
  const [rightsAttested, setRightsAttested] = useState(false);
  useEffect(() => setDraft(initial), [initial]);
  const totalChars = useMemo(() => draft.scenes.reduce((sum, scene) => sum + scene.narration.length, 0), [draft]);
  const change = (index: number, scene: Scene) => setDraft({...draft, scenes: draft.scenes.map((item, i) => i === index ? scene : item)});
  const move = (index: number, direction: -1 | 1) => {const scenes = [...draft.scenes]; const target = index + direction; [scenes[index], scenes[target]] = [scenes[target], scenes[index]]; setDraft({...draft, scenes: scenes.map((scene, ordinal) => ({...scene, ordinal}))});};
  const duplicate = (index: number) => {const source = draft.scenes[index]; const copy = {...structuredClone(source), id: "", title: `${source.title}（副本）`, verified: false, assets: []}; const scenes = [...draft.scenes]; scenes.splice(index + 1, 0, copy); setDraft({...draft, scenes: scenes.map((scene, ordinal) => ({...scene, ordinal}))});};
  return (
    <section className="panel storyboard-panel">
      <div className="section-heading sticky"><div><span className="step-number">03</span><div><h2>审核场景卡</h2><p>{draft.scenes.length} 个场景 · {totalChars} 字旁白 · 预计费用 US${draft.estimated_cost_usd.toFixed(2)}</p></div></div><div><button className="secondary" disabled={busy} onClick={() => onSave(draft)}>保存并核验</button>{project.status !== "completed" ? <button className="primary" disabled={busy || draft.scenes.some((scene) => !scene.verified)} onClick={onApprove}>批准并生成 →</button> : null}</div></div>
      <div className="blueprint-settings"><label>目标平台<select value={draft.target_platform} onChange={(event) => setDraft({...draft, target_platform: event.target.value})}><option>通用竖屏</option><option>抖音</option><option>视频号</option><option>小红书</option></select></label><label>表达风格<input value={draft.style} onChange={(event) => setDraft({...draft, style: event.target.value})} /></label><label>配音音色<select value={draft.speech_voice} onChange={(event) => setDraft({...draft, speech_voice: event.target.value as Storyboard["speech_voice"]})}><option value="alloy">Alloy</option><option value="echo">Echo</option><option value="fable">Fable</option><option value="onyx">Onyx</option><option value="nova">Nova</option><option value="shimmer">Shimmer</option></select></label></div>
      <div className="music-control"><label className="file-button secondary">选择背景音乐<input type="file" accept="audio/mpeg,.mp3" onChange={(event) => setMusic(event.target.files?.[0] ?? null)} /></label><span>{music?.name ?? "默认关闭背景音乐"}</span><label><input type="checkbox" checked={rightsAttested} onChange={(event) => setRightsAttested(event.target.checked)} /> 我确认拥有该音乐的使用权</label><button className="secondary" disabled={busy || !music || !rightsAttested} onClick={async () => {if (!music) return; await onMusicUpload(music); setMusic(null); setRightsAttested(false);}}>上传音乐</button></div>
      <div className="scene-list">{draft.scenes.map((scene, index) => <SceneCard key={scene.id || `new-${index}`} scene={scene} index={index} total={draft.scenes.length} busy={busy} onChange={(next) => change(index, next)} onMove={(direction) => move(index, direction)} onDuplicate={() => duplicate(index)} onDelete={() => setDraft({...draft, scenes: draft.scenes.filter((_, i) => i !== index).map((item, ordinal) => ({...item, ordinal}))})} onRegenerate={(target) => onRegenerate(scene.id, target)} onImageUpload={(file) => onImageUpload(scene.id, file)} />)}</div>
    </section>
  );
}

function CompletedPanel({project, board, exports}: {project: Project; board: Storyboard; exports: ExportItem[]}) {
  return (
    <section className="panel completed-panel">
      <div className="section-heading"><div><span className="step-number done">✓</span><div><h2>发布包已完成</h2><p>视频、音频、字幕、封面、故事板、来源和平台文案都保存在本地。</p></div></div></div>
      <div className="completed-grid"><VideoPreview project={project} board={board} /><div className="export-list"><h3>下载文件</h3>{exports.map((item) => <a key={item.name} href={`${API_URL}${item.url}`}><span>{item.name}</span><small>{(item.size / 1024 / 1024).toFixed(2)} MB</small><b>↓</b></a>)}</div></div>
    </section>
  );
}
