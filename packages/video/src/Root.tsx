import React from "react";
import {Composition} from "remotion";
import {Cover, LiteraryVideo} from "./LiteraryVideo";
import {LiteraryVideoPropsSchema, totalDurationInFrames, type LiteraryVideoProps} from "./types";

const defaults: LiteraryVideoProps = {
  title: "文学解读",
  style: "冷静、深刻、不卖弄",
  aiVoiceDisclosure: "本内容使用 AI 合成语音",
  musicSrc: null,
  scenes: [
    {
      id: "preview",
      title: "序章",
      narration: "一部经典，为什么直到今天仍然让人不安？",
      onScreenText: "经典不是答案，而是一面镜子",
      visualType: "text_card",
      imageSrc: null,
      audioSrc: null,
      durationInFrames: 180,
      sourceLabel: "演示来源",
      captions: [{start: 0, end: 6, text: "一部经典，为什么直到今天仍然让人不安？"}],
    },
  ],
};

export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="LiteraryVideo"
      component={LiteraryVideo}
      width={1080}
      height={1920}
      fps={30}
      durationInFrames={180}
      schema={LiteraryVideoPropsSchema}
      defaultProps={defaults}
      calculateMetadata={({props}) => ({durationInFrames: totalDurationInFrames(props)})}
    />
    <Composition
      id="LiteraryCover"
      component={Cover}
      width={1080}
      height={1920}
      fps={30}
      durationInFrames={1}
      schema={LiteraryVideoPropsSchema}
      defaultProps={defaults}
    />
  </>
);
