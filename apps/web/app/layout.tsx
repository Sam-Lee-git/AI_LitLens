import type {Metadata} from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "墨镜 · AI 文学解读 Agent",
  description: "把一本书变成有出处、可编辑、可发布的视听内容",
};

export default function RootLayout({children}: Readonly<{children: React.ReactNode}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
