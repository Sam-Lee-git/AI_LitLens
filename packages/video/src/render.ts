import path from "node:path";
import {fileURLToPath} from "node:url";
import {readFile, mkdir} from "node:fs/promises";
import {bundle} from "@remotion/bundler";
import {renderMedia, renderStill, selectComposition} from "@remotion/renderer";
import {LiteraryVideoPropsSchema} from "./types";

const valueAfter = (flag: string): string => {
  const index = process.argv.indexOf(flag);
  if (index < 0 || !process.argv[index + 1]) throw new Error(`缺少参数 ${flag}`);
  return process.argv[index + 1];
};

const inputPath = path.resolve(valueAfter("--input"));
const outputDir = path.resolve(valueAfter("--output"));
const raw = JSON.parse(await readFile(inputPath, "utf8"));
const inputProps = LiteraryVideoPropsSchema.parse(raw);
await mkdir(outputDir, {recursive: true});

const here = path.dirname(fileURLToPath(import.meta.url));
const serveUrl = await bundle({
  entryPoint: path.join(here, "entry.ts"),
  publicDir: raw.publicDir,
  onProgress: () => undefined,
});
const composition = await selectComposition({
  serveUrl,
  id: "LiteraryVideo",
  inputProps,
});

await renderMedia({
  composition,
  serveUrl,
  codec: "h264",
  audioCodec: "aac",
  outputLocation: path.join(outputDir, "video.mp4"),
  inputProps,
  overwrite: true,
});

const cover = await selectComposition({serveUrl, id: "LiteraryCover", inputProps});
await renderStill({
  composition: cover,
  serveUrl,
  output: path.join(outputDir, "cover.png"),
  inputProps,
  imageFormat: "png",
});
