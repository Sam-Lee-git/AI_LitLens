import type {Metadata} from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "墨镜 · AI 文学解读 Agent",
  description: "输入名著名称，让 AI 生成可编辑、可发布的文学解读内容",
};

export default function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
