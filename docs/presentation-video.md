# PPT 讲解视频

该独立命令行入口复用项目的 OpenAI 配音服务与 Remotion 渲染包，不修改文学竖屏工作流，也不包含社交平台发布功能。

## 输入

先在 Windows 使用 PowerPoint 的文件导出接口创建只读快照与逐页 PNG。不会保存或修改原 PPT，也不会使用已有目录里可能过期的预览。

```powershell
powershell.exe -NoProfile -File services/api/scripts/export_presentation.ps1 -Source "D:/path/deck.pptx" -Output "D:/path/work"
```

工作目录中的 `deck.json` 保存源文件 SHA256、实际页数及顺序。根据 PPT 正文与演讲备注编写 `narration.json`：

```json
{
  "title": "演示文稿标题",
  "sourceSha256": "填写 deck.json 中的 sourceSha256",
  "editorialMode": "依据PPT正文及备注编写的讲解，保留示意与假设限定。",
  "slides": [
    {"number": 1, "title": "第一页", "lines": ["第一句讲解。", "第二句讲解。"]}
  ]
}
```

句子必须为 1–100 字。脚本需覆盖实际全部页面，不能依据文件名推断页数。讲稿需要内容审核，不会自动声称已核验 PPT 中的所有外部引用。

## 生成与检查

在仓库根目录运行，沿用 `.env` 中的后端 API 密钥与声音配置。

```powershell
.venv/Scripts/python.exe services/api/scripts/render_presentation.py --work-dir "D:/path/work" --stage media
.venv/Scripts/python.exe services/api/scripts/render_presentation.py --work-dir "D:/path/work" --stage preview
# 检查 work/qa 中的全部预览帧后渲染
.venv/Scripts/python.exe services/api/scripts/render_presentation.py --work-dir "D:/path/work" --stage render
```

静态PPT可将最后一步替换为 `--stage render-fast`。该路径用 Remotion 渲染每个不同字幕画面，再由 FFmpeg 按精确帧数保持画面、添加翻页淡入淡出并编码。它复用相同的配音与字幕时间轴，逐页缓存成功的编码结果，适合较长演示。

逐句配音按模型、声音与文本的哈希缓存。修改讲稿后重新运行 media 阶段，只为变化的句子调用配音接口。没有密钥就明确报错，不回退到静音或模拟声音。当前费用估算只支持 `tts-1` 和 `tts-1-hd`，首次语音估算不得超过项目预算或 US$1；不是账单查询，重试可能另外产生费用。

画面为 1920×1080、30 FPS，保持整页比例，在独立底栏显示字幕、页码和 AI 配音披露。页面使用轻量淡入淡出，不裁切或重排原图表。不保留 PPT 的对象动画、交互、内嵌音视频播放或点击逻辑。

产物位于 `exports/`：`video.mp4`、`narration.mp3`、`captions.srt`、`cover.png`、`script.md`、`storyboard.json`、`chapters.txt`、`sources.md`、`manifest.json`。视频嵌入章节。源 PPT 快照、句级音频与诊断文件留在私有工作目录，不加入导出包。

渲染后自动检查编码、画幅、帧率、时长、字幕区间、音轨音量并全片解码。原始文件、旁白、缓存及成品应放在 gitignored 的 `data/` 中，不能把内部演示资料提交到仓库。

## 边界

- 这是独立 PPT 转视频入口，不是 Web UI 中的通用 PPT 导入功能。
- 页面导出需要 Windows PowerPoint；导出后的 PNG、讲稿、配音及 Remotion 流程可移至其他系统，中文字体需要自行配置。
- 本地预览和已授权的配音接口不等于对外发布授权。
