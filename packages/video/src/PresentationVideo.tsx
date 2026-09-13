import React from "react";
import {AbsoluteFill, Audio, Img, Sequence, interpolate, staticFile, useCurrentFrame} from "remotion";
import {type PresentationProps, type PresentationSlide} from "./presentation-types";

const Slide: React.FC<{slide: PresentationSlide; count: number}> = ({slide, count}) => {
  const frame = useCurrentFrame();
  const seconds = frame / 30;
  const caption = slide.captions.find((item) => seconds >= item.start && seconds < item.end);
  const opacity = interpolate(frame, [0, 10, slide.durationInFrames - 10, slide.durationInFrames - 1],
    [0, 1, 1, 0], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return <AbsoluteFill style={{backgroundColor: "white", fontFamily: '"Microsoft YaHei", "Noto Sans CJK SC", sans-serif'}}>
    <div style={{position: "absolute", top: 0, left: 0, width: 1920, height: 980, opacity}}>
      <Img src={staticFile(slide.imageSrc)} style={{width: "100%", height: "100%", objectFit: "contain"}} />
    </div>
    <div style={{position: "absolute", bottom: 0, height: 100, width: "100%", backgroundColor: "#202329",
      borderTop: "3px solid #a40000", color: "white", display: "flex", alignItems: "center"}}>
      <div style={{width: 155, flexShrink: 0, textAlign: "center", fontSize: 22, color: "#d5d6d8"}}>
        {String(slide.number).padStart(2, "0")} / {String(count).padStart(2, "0")}
      </div>
      <div style={{flex: 1, fontSize: 32, lineHeight: 1.32, textAlign: "center", whiteSpace: "pre-wrap", textWrap: "balance",
        overflowWrap: "anywhere", maxHeight: 88, overflow: "hidden"}}>{caption?.text ?? ""}</div>
      <div style={{width: 155, flexShrink: 0, textAlign: "center", fontSize: 20, color: "#d5d6d8"}}>AI 合成配音</div>
    </div>
  </AbsoluteFill>;
};

export const PresentationVideo: React.FC<PresentationProps> = ({slides, audioSrc}) => {
  let start = 0;
  return <AbsoluteFill style={{backgroundColor: "white"}}>
    {audioSrc ? <Audio src={staticFile(audioSrc)} /> : null}
    {slides.map((slide) => {
      const from = start;
      start += slide.durationInFrames;
      return <Sequence key={slide.number} from={from} durationInFrames={slide.durationInFrames}>
        <Slide slide={slide} count={slides.length} />
      </Sequence>;
    })}
  </AbsoluteFill>;
};
