import {describe, expect, it} from "vitest";
import {LiteraryVideoPropsSchema, totalDurationInFrames} from "./types";

describe("video contract", () => {
  it("validates scenes and calculates the exact duration", () => {
    const value = LiteraryVideoPropsSchema.parse({
      title: "测试",
      style: "克制",
      scenes: [
        {
          id: "a",
          title: "开场",
          narration: "旁白",
          onScreenText: "标题",
          visualType: "text_card",
          imageSrc: null,
          audioSrc: null,
          durationInFrames: 90,
          sourceLabel: "第1页",
          captions: [{start: 0, end: 3, text: "旁白"}],
        },
        {
          id: "b",
          title: "结尾",
          narration: "结论",
          onScreenText: "结论",
          visualType: "quote_card",
          imageSrc: null,
          audioSrc: null,
          durationInFrames: 120,
          sourceLabel: "第2页",
          captions: [{start: 0, end: 4, text: "结论"}],
        },
      ],
    });
    expect(totalDurationInFrames(value)).toBe(210);
  });
});
