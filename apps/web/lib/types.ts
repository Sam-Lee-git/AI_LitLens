export type ProjectStatus =
  | "draft"
  | "sources_ready"
  | "analyzing"
  | "angles_ready"
  | "storyboard_review"
  | "approved"
  | "generating_media"
  | "rendering"
  | "completed"
  | "failed";

export interface Source {
  id: string;
  kind: "primary" | "supplement";
  source_type: string;
  title: string;
  original_filename: string | null;
  char_count: number;
  created_at: string;
}

export interface Angle {
  id: string;
  ordinal: number;
  title: string;
  hook: string;
  thesis: string;
  audience_value: string;
  evidence_block_ids: string[];
}

export interface Project {
  id: string;
  title: string;
  description: string;
  status: ProjectStatus;
  language: string;
  target_platform: string;
  style: string;
  selected_angle_id: string | null;
  storyboard_revision: number;
  estimated_cost_usd: number;
  created_at: string;
  updated_at: string;
  sources: Source[];
  angles: Angle[];
}

export interface Citation {
  id: string;
  block_id: string;
  claim_type: "fact" | "quote" | "interpretation";
  quote: string;
  verified: boolean;
  confidence: number;
  locator: Record<string, unknown> | null;
  source_title: string | null;
}

export interface SceneAsset {
  id: string;
  kind: "audio" | "image" | "music";
  stale: boolean;
  duration_seconds: number | null;
  url: string;
}

export interface Scene {
  id: string;
  ordinal: number;
  title: string;
  narration: string;
  on_screen_text: string;
  visual_type: "illustration" | "quote_card" | "text_card" | "relationship_card";
  visual_prompt: string;
  duration_seconds: number;
  verified: boolean;
  revision: number;
  citations: Citation[];
  assets: SceneAsset[];
}

export interface Storyboard {
  project_id: string;
  revision: number;
  target_platform: string;
  style: string;
  speech_voice: "alloy" | "echo" | "fable" | "onyx" | "nova" | "shimmer";
  estimated_cost_usd: number;
  scenes: Scene[];
}

export interface ExportItem {
  name: string;
  size: number;
  url: string;
}

export interface ProgressEvent {
  id: number;
  kind: string;
  message: string;
  progress: number;
  data: Record<string, unknown>;
}
