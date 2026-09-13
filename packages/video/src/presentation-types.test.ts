import {describe, expect, it} from "vitest";
import {PresentationPropsSchema, presentationFrames} from "./presentation-types";

const sample = () => ({title: "演示", audioSrc: "narration.wav", slides: [
  {number: 1, title: "第一页", imageSrc: "slide-01.png", durationInFrames: 180,
    captions: [{start: 0.5, end: 5.5, text: "依据PPT的中文讲解"}]},
]});
describe("presentation video", () => {
  it("preserves the frame-aligned page duration", () => {
    expect(presentationFrames(PresentationPropsSchema.parse(sample()))).toBe(180);
  });
  it("rejects captions past the slide boundary", () => {
    const value = sample(); value.slides[0].captions[0].end = 7;
    expect(() => PresentationPropsSchema.parse(value)).toThrow();
  });
  it("rejects overlapping captions", () => {
    const value = sample(); value.slides[0].captions.push({start: 4, end: 6, text: "重叠"});
    expect(() => PresentationPropsSchema.parse(value)).toThrow();
  });
});
