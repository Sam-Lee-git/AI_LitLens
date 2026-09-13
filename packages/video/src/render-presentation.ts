import path from "node:path";
import {fileURLToPath} from "node:url";
import {readFile, mkdir, writeFile} from "node:fs/promises";
import {bundle} from "@remotion/bundler";
import {openBrowser, renderMedia, renderStill, selectComposition} from "@remotion/renderer";
import {PresentationPropsSchema} from "./presentation-types";

const option = (flag: string): string => {
  const index = process.argv.indexOf(flag);
  if (index < 0 || !process.argv[index + 1]) throw new Error(`Missing ${flag}`);
  return process.argv[index + 1];
};
const input = path.resolve(option("--input"));
const output = path.resolve(option("--output"));
const props = PresentationPropsSchema.parse(JSON.parse(await readFile(input, "utf8")));
if (!props.publicDir) throw new Error("publicDir is required for local slide assets");
await mkdir(output, {recursive: true});
const serveUrl = await bundle({entryPoint: path.join(path.dirname(fileURLToPath(import.meta.url)), "presentation-entry.tsx"),
  publicDir: props.publicDir, onProgress: () => undefined});
const composition = await selectComposition({serveUrl, id: "PresentationVideo", inputProps: props});
if (process.argv.includes("--stills")) {
  const browser = await openBrowser("chrome");
  const jobs: Array<() => Promise<void>> = [];
  const pages: Array<{number: number; durationInFrames: number; intervals: Array<{file: string; frames: number}>}> = [];
  let cursor = 0;
  for (const slide of props.slides) {
    const pageStart = cursor;
    const emptyName = `page-${slide.number}-empty.png`;
    const noCaptions = {...props, audioSrc: null, slides: props.slides.map((s) => ({...s, captions: []}))};
    jobs.push(() => renderStill({composition, serveUrl, puppeteerInstance: browser, inputProps: noCaptions,
      frame: pageStart + 15, output: path.join(output, emptyName), imageFormat: "png"}).then(() => undefined));
    const intervals: Array<{file: string; frames: number}> = [];
    let position = 0;
    for (const [index, caption] of slide.captions.entries()) {
      const start = Math.ceil(caption.start * 30 - 1e-7);
      const end = Math.ceil(caption.end * 30 - 1e-7);
      if (start > position) intervals.push({file: emptyName, frames: start - position});
      const name = `page-${slide.number}-caption-${index + 1}.png`;
      intervals.push({file: name, frames: end - start});
      jobs.push(() => renderStill({composition, serveUrl, puppeteerInstance: browser,
        inputProps: {...props, audioSrc: null}, frame: pageStart + start,
        output: path.join(output, name), imageFormat: "png"}).then(() => undefined));
      position = end;
    }
    if (position < slide.durationInFrames) intervals.push({file: emptyName, frames: slide.durationInFrames - position});
    pages.push({number: slide.number, durationInFrames: slide.durationInFrames, intervals});
    cursor += slide.durationInFrames;
  }
  try {
    for (let index = 0; index < jobs.length; index += 3) {
      await Promise.all(jobs.slice(index, index + 3).map((job) => job()));
      console.log(`Cached frames ${Math.min(index + 3, jobs.length)}/${jobs.length}`);
    }
    await writeFile(path.join(output, "timelines.json"), JSON.stringify(pages, null, 2));
  } finally {
    await browser.close({silent: true});
  }
} else if (process.argv.includes("--preview")) {
  let cursor = 0;
  for (const slide of props.slides) {
    await renderStill({composition, serveUrl, inputProps: props, frame: cursor + Math.min(60, slide.durationInFrames - 1),
      output: path.join(output, `page-${String(slide.number).padStart(2, "0")}.png`), imageFormat: "png"});
    cursor += slide.durationInFrames;
    console.log(`Preview ${slide.number}/${props.slides.length}`);
  }
} else {
  let last = -1;
  await renderMedia({composition, serveUrl, inputProps: props, outputLocation: path.join(output, "video.rendering.mp4"),
    codec: "h264", audioCodec: "aac", audioBitrate: "192k", crf: 18, x264Preset: "veryfast",
    pixelFormat: "yuv420p", concurrency: 4, overwrite: true,
    onProgress: ({progress}) => {
      const percent = Math.floor(progress * 100);
      if (percent > last) { last = percent; console.log(`Render ${percent}%`); }
    }});
}
