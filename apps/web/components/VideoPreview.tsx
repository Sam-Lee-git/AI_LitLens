"use client";

import {LiteraryVideo, type LiteraryVideoProps} from "@content-agent/video";
import {Player} from "@remotion/player";
import {API_URL} from "@/lib/api";
import type {Project, Storyboard} from "@/lib/types";

export function VideoPreview({project, board}: {project: Project; board: Storyboard}) {
  const props: LiteraryVideoProps = {
    title: project.title,
    style: board.style,
    musicSrc: null,
    aiVoiceDisclosure: "本内容使用 AI 合成语音",
    scenes: board.scenes.map((scene) => {
      const image = scene.assets.find((asset) => asset.kind === "image" && !asset.stale);
      const audio = scene.assets.find((asset) => asset.kind === "audio" && !asset.stale);
      const duration = audio?.duration_seconds ?? scene.duration_seconds;
      return {
        id: scene.id,
        title: scene.title,
        narration: scene.narration,
        onScreenText: scene.on_screen_text,
        visualType: scene.visual_type,
        imageSrc: image ? `${API_URL}${image.url}` : null,
        audioSrc: audio ? `${API_URL}${audio.url}` : null,
        durationInFrames: Math.max(90, Math.round(duration * 30)),
        sourceLabel: scene.citations[0]?.source_title
          ? `《${scene.citations[0].source_title}》`
          : "来源待核验",
        captions: [{start: 0, end: duration, text: scene.narration}],
      };
    }),
  };
  const duration = props.scenes.reduce((sum, scene) => sum + scene.durationInFrames, 0);
  return (
    <div className="preview-shell">
      <Player
        component={LiteraryVideo}
        inputProps={props}
        durationInFrames={duration}
        compositionWidth={1080}
        compositionHeight={1920}
        fps={30}
        controls
        style={{width: "100%", aspectRatio: "9 / 16"}}
      />
    </div>
  );
}
