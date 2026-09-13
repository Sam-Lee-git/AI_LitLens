import {z} from "zod";

export const PresentationCaptionSchema = z.object({
  start: z.number().nonnegative(),
  end: z.number().positive(),
  text: z.string().min(1).max(100),
});
export const PresentationSlideSchema = z.object({
  number: z.number().int().positive(),
  title: z.string(),
  imageSrc: z.string(),
  durationInFrames: z.number().int().min(30),
  captions: z.array(PresentationCaptionSchema),
}).superRefine((slide, ctx) => {
  let previousEnd = 0;
  for (const caption of slide.captions) {
    if (caption.start < previousEnd - 0.001 || caption.end <= caption.start ||
        caption.end > slide.durationInFrames / 30 + 0.001) {
      ctx.addIssue({code: z.ZodIssueCode.custom, message: "Invalid or overlapping caption timing"});
    }
    previousEnd = caption.end;
  }
});
export const PresentationPropsSchema = z.object({
  title: z.string(),
  audioSrc: z.string().nullable(),
  slides: z.array(PresentationSlideSchema).min(1),
  publicDir: z.string().optional(),
});
export type PresentationProps = z.infer<typeof PresentationPropsSchema>;
export type PresentationSlide = z.infer<typeof PresentationSlideSchema>;
export const presentationFrames = (props: PresentationProps): number =>
  props.slides.reduce((sum, slide) => sum + slide.durationInFrames, 0);
