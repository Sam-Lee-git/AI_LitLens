# AI 文学解读内容 Agent

一个简体中文、本地单用户的内容生产工具：导入 PDF/EPUB 和补充笔记，生成带来源的解读角度、可编辑场景卡、AI 配音与插画，并渲染为 9:16 视频发布包。

## 快速开始（Windows PowerShell）

```powershell
Copy-Item .env.example .env
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e "./services/api[dev]"
npm install
npm run doctor
npm run dev
```

打开 `http://127.0.0.1:3000`。如果 `.env` 中没有 `OPENAI_API_KEY`，应用会自动使用确定性的演示提供器，不产生 API 费用；配置密钥后使用 OpenAI Responses、Image 和 Speech API。

## 工作流

1. 新建项目并上传一份文字型 PDF 或 EPUB。
2. 可添加最多五份补充笔记。
3. 分析资料并选择一个解读角度。
4. 审核、编辑和排序场景卡。
5. 确认预算后生成媒体和发布包。

运行时数据存放在 `data/`，不会提交到 Git。API 密钥只由 Python 后端读取。

## 常用命令

```powershell
npm run dev
npm run test
npm run build
npm run doctor
npm run worker:once
npm run e2e:mock
```

`npm run e2e:mock -- --count 3` 会连续完成三条 mock 作品，并用 FFprobe 验证发布包、编码、分辨率、帧率、音轨与 3–5 分钟时长；不会调用付费 API。
`npm run e2e:mock -- --existing-project <项目ID>` 会修改一个场景、重渲染并断言其余媒体资源校验值保持不变。

Remotion 在本 MVP 中用于个人本地内容生产。将产品改造成公开 SaaS 或批量自动化服务前，请重新核对 Remotion 商业授权。
