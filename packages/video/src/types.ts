import {z} from "zod";

export const CaptionSchema = z.object({
  start: z.number().nonnegative(),
  end: z.number().positive(),
  text: z.string(),
});

export const VideoSceneSchema = z.object({
  id: z.string(),
  title: z.string(),
  narration: z.string(),
  onScreenText: z.string(),
  visualType: z.enum(["illustration", "quote_card", "text_card", "relationship_card"]),
  imageSrc: z.string().nullable(),
  audioSrc: z.string().nullable(),
  durationInFrames: z.number().int().positive(),
  sourceLabel: z.string(),
  captions: z.array(CaptionSchema),
});

export const LiteraryVideoPropsSchema = z.object({
  title: z.string(),
  style: z.string(),
  scenes: z.array(VideoSceneSchema).min(1),
  musicSrc: z.string().nullable().optional(),
  aiVoiceDisclosure: z.string().default("本内容使用 AI 合成语音"),
  publicDir: z.string().optional(),
});

export type Caption = z.infer<typeof CaptionSchema>;
export type VideoScene = z.infer<typeof VideoSceneSchema>;
export type LiteraryVideoProps = z.infer<typeof LiteraryVideoPropsSchema>;

export const totalDurationInFrames = (props: LiteraryVideoProps): number =>
  props.scenes.reduce((total, scene) => total + scene.durationInFrames, 0);
