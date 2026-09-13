# 《罪与罚》试播样片

本样片用于检验“故事框架 + 一个观点 + 图片/文字/声音”的内容形态。
讲稿由 Codex 编写并依据原著章节核对，插画由内置 imagegen 生成，配音使用项目后端的真实 OpenAI Speech Provider。
它不是无人审核的书名到视频验收，也不代表已经完成连续三条视频验收。

## 内容与素材

- 讲稿：`examples/crime-and-punishment-pilot.json`，14 段、49 句、约 1,284 字。
- 核心观点：自认卓越不能赋予一个人把他人当作代价的权利。
- 故事框架、两个论据、人物复杂性、认罪与悔悟的区别，以及当代类比的边界均已写入讲稿。
- 原著依据：[Project Gutenberg #2554](https://www.gutenberg.org/ebooks/2554)，Constance Garnett 英译；中文旁白为转述与原创分析，不冒充中文译本引文。
- 六张统一油画/炭笔风格的意象插画；提示词随发布包保存。没有使用影视改编画面。
- 配音：`tts-1-hd` / `alloy`。按句生成，按真实 PCM 采样数对齐字幕，并将场景边界补齐到 30 FPS。
- 实际内容时长：271.833 秒；无背景音乐。

## 本机复现

从仓库根目录运行。需要已经配置的后端密钥，不要把密钥写入命令或发布包。

```powershell
.\.venv\Scripts\python.exe services/api/scripts/render_reviewed_pilot.py --reviewed --stage media
.\.venv\Scripts\python.exe services/api/scripts/render_reviewed_pilot.py --reviewed --stage preview
.\.venv\Scripts\python.exe services/api/scripts/render_reviewed_pilot.py --reviewed --stage render
.\.venv\Scripts\python.exe services/api/scripts/verify_reviewed_pilot.py
```

`data/pilots/crime-and-punishment/state.json` 记录本机项目 ID。
`reference.html`、`images/`、`image-prompts.json` 与语音缓存位于同一试播目录，均不提交 Git。
另一台机器不能只拉取代码就生成相同样片；需要自行准备这些素材或通过产品生成新的项目。

`media` 会按模型、声音和句子内容的哈希复用语音缓存，缺失语音才会付费调用；图片由已有本机素材导入。
`preview` 只生成静帧和封面；`render` 复用现有媒体，不生成新语音和插画。
本固定样片不允许静默覆盖已保存的讲稿版本；修改讲稿应另建修订，避免把旧配音误当作新内容。

## 交付和验证

项目的 `exports/` 包含视频、纯旁白、SRT、封面、分镜、原著定位、完整讲稿、发布文案、图片提示词和 manifest。
视频与发布文案均披露 AI 配音、AI 插画及剧透。
发布包不包含原著全文、上传文件、密钥或语音请求日志。

验证脚本检查文件哈希、1080×1920 / 30 FPS / H.264 / AAC、3–5 分钟时长、音画时长一致、49 句字幕边界连续、章节引用、非静音音轨和全片可解码性，并导出 14 个抽查帧。
验证结果写入本机项目的 `qa/verification.json`，不能用单元测试通过替代成片检查。

费用不假装精确：记录语音字符和图片数量，实际扣费以账户账单为准；内置图片工具的费用不冒充后端 API 用量。

## 本次实测结果

- 本机项目 ID：`557971cd-619e-4c7b-8429-c5495fc57f40`。
- 完整 MP4 渲染成功；容器时长 271.893 秒，画面 8,155 帧 / 271.833 秒。
- 最终 MP4、纯旁白、49 句 SRT 和 manifest 哈希检查均通过；全片 FFmpeg 解码通过，14 段抽查帧无裁切溢出。
- MP4 配音增加 6 dB，纯旁白增加 3 dB；最终视频均值 -21.3 dB、峰值 -2.8 dB。图像帧未重编码，调整前文件保存在项目 `mastering-originals/`，不随发布包导出。
- 输出为 8-bit full-range 4:2:0（FFprobe 显示 `yuvj420p`），不是 4:4:4 或 10-bit 输出。
- 渲染收尾时出现过 `Page.bringToFront: Target closed` 日志，但进程退出码为 0，随后独立完成上述媒体检查；不能仅凭退出码忽略该日志。
- 后端测试、视频单元测试、TypeScript 类型检查通过。没有把这些测试当成文学质量或全自动生产验收。
- 发布包：`data/pilots/crime-and-punishment/CrimeAndPunishment-Pilot.zip`。
