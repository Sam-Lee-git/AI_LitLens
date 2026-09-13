import React from "react";
import {
  AbsoluteFill,
  Audio,
  Img,
  interpolate,
  Series,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type {LiteraryVideoProps, VideoScene} from "./types";
import {totalDurationInFrames} from "./types";

const COLORS = {
  ink: "#121119",
  paper: "#f2eadb",
  muted: "#bdb4a6",
  gold: "#cda962",
  plum: "#442f48",
};

const assetUrl = (src: string): string =>
  /^(https?:|data:|blob:)/.test(src) ? src : staticFile(src.replace(/^\//, ""));

const Backdrop: React.FC<{scene: VideoScene}> = ({scene}) => {
  const frame = useCurrentFrame();
  const progress = interpolate(frame, [0, scene.durationInFrames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  if (scene.imageSrc) {
    return (
      <AbsoluteFill style={{overflow: "hidden", backgroundColor: COLORS.ink}}>
        <Img
          src={assetUrl(scene.imageSrc)}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            transform: `scale(${1.06 + progress * 0.08}) translateY(${progress * -1.5}%)`,
            filter: "saturate(.86) contrast(1.04) brightness(.92)",
          }}
        />
        <AbsoluteFill
          style={{
            background:
              "linear-gradient(180deg, rgba(18,17,25,.12) 0%, rgba(18,17,25,.35) 48%, rgba(18,17,25,.95) 100%)",
          }}
        />
      </AbsoluteFill>
    );
  }
  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(circle at ${28 + progress * 20}% 28%, ${COLORS.plum}, ${COLORS.ink} 56%)`,
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 110,
          border: `2px solid ${COLORS.gold}55`,
          borderRadius: 60,
          transform: `rotate(${progress * 1.2 - 0.6}deg)`,
        }}
      />
    </AbsoluteFill>
  );
};

const SceneView: React.FC<{scene: VideoScene; sceneNumber: number}> = ({scene, sceneNumber}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const seconds = frame / fps;
  const caption = scene.captions.find((item) => seconds >= item.start && seconds < item.end);
  const entrance = interpolate(frame, [0, 18], [40, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const opacity = interpolate(frame, [0, 15, scene.durationInFrames - 12, scene.durationInFrames], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill style={{fontFamily: '"Microsoft YaHei", "Noto Sans SC", sans-serif', color: COLORS.paper}}>
      <Backdrop scene={scene} />
      <div style={{position: "absolute", top: 110, left: 88, right: 88, display: "flex", alignItems: "center", gap: 20}}>
        <span style={{fontSize: 26, color: COLORS.gold, letterSpacing: 4}}>{String(sceneNumber).padStart(2, "0")}</span>
        <div style={{height: 2, flex: 1, background: `${COLORS.gold}66`}} />
        <span style={{fontSize: 22, color: COLORS.muted}}>文学解读</span>
      </div>
      <div
        style={{
          position: "absolute",
          left: 88,
          right: 88,
          top: scene.imageSrc ? 840 : 470,
          opacity,
          transform: `translateY(${entrance}px)`,
        }}
      >
        <div style={{fontSize: 30, color: COLORS.gold, marginBottom: 24, letterSpacing: 3}}>{scene.title}</div>
        <div style={{fontFamily: '"STSong", "SimSun", serif', fontSize: 70, lineHeight: 1.35, fontWeight: 650, whiteSpace: "pre-line", textShadow: "0 6px 28px #000"}}>
          {scene.onScreenText}
        </div>
      </div>
      <div
        style={{
          position: "absolute",
          left: 74,
          right: 74,
          bottom: 184,
          minHeight: 132,
          padding: "28px 34px",
          borderRadius: 30,
          backgroundColor: "rgba(9, 9, 14, .78)",
          border: "1px solid rgba(255,255,255,.1)",
          fontSize: 37,
          lineHeight: 1.55,
          textAlign: "center",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {caption?.text ?? scene.narration}
      </div>
      <div style={{position: "absolute", left: 88, right: 88, bottom: 88, display: "flex", justifyContent: "space-between", fontSize: 20, color: COLORS.muted}}>
        <span>{scene.sourceLabel}</span>
        <span>AI 辅助制作</span>
      </div>
      {scene.audioSrc ? <Audio src={assetUrl(scene.audioSrc)} /> : null}
    </AbsoluteFill>
  );
};

export const LiteraryVideo: React.FC<LiteraryVideoProps> = (props) => {
  const frame = useCurrentFrame();
  const total = totalDurationInFrames(props);
  const musicVolume = interpolate(frame, [0, 60, Math.max(61, total - 90), total], [0, 0.1, 0.1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill style={{backgroundColor: COLORS.ink}}>
      {props.musicSrc ? <Audio loop src={assetUrl(props.musicSrc)} volume={musicVolume} /> : null}
      <Series>
        {props.scenes.map((scene, index) => (
          <Series.Sequence key={scene.id} durationInFrames={scene.durationInFrames}>
            <SceneView scene={scene} sceneNumber={index + 1} />
          </Series.Sequence>
        ))}
      </Series>
      <div style={{position: "absolute", top: 50, right: 62, fontSize: 16, color: "rgba(255,255,255,.46)", fontFamily: "sans-serif"}}>
        {props.aiVoiceDisclosure}
      </div>
    </AbsoluteFill>
  );
};

export const Cover: React.FC<LiteraryVideoProps> = ({title, scenes}) => {
  const first = scenes[0];
  return (
    <AbsoluteFill style={{fontFamily: '"Microsoft YaHei", sans-serif', color: COLORS.paper, backgroundColor: COLORS.ink}}>
      <Backdrop scene={first} />
      <div style={{position: "absolute", inset: "280px 90px 220px", display: "flex", flexDirection: "column", justifyContent: "center"}}>
        <div style={{fontSize: 30, color: COLORS.gold, letterSpacing: 8, marginBottom: 36}}>深度文学解读</div>
        <div style={{fontFamily: '"STSong", "SimSun", serif', fontSize: 94, lineHeight: 1.2, fontWeight: 700, textShadow: "0 8px 34px #000"}}>{title}</div>
        <div style={{marginTop: 42, width: 160, height: 5, backgroundColor: COLORS.gold}} />
        <div style={{marginTop: 36, fontSize: 44, lineHeight: 1.45, whiteSpace: "pre-line"}}>{first.onScreenText}</div>
      </div>
    </AbsoluteFill>
  );
};
