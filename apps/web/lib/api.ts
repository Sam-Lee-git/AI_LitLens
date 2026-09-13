import type {ExportItem, Project, Storyboard} from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(typeof detail === "string" ? detail : "请求失败");
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_URL}${path}`, {...init, headers});
  if (!response.ok) {
    const payload = await response.json().catch(() => ({detail: response.statusText}));
    throw new ApiError(response.status, payload.detail ?? payload);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const projectApi = {
  list: () => api<Project[]>("/projects"),
  get: (id: string) => api<Project>(`/projects/${id}`),
  create: (title: string, description: string) =>
    api<Project>("/projects", {
      method: "POST",
      body: JSON.stringify({title, description, auto_analyze: true}),
    }),
  remove: (id: string) => api<void>(`/projects/${id}`, {method: "DELETE"}),
  analyze: (id: string) => api(`/projects/${id}/analyze`, {method: "POST"}),
  chooseAngle: (id: string, angleId: string) =>
    api(`/projects/${id}/angle`, {method: "PUT", body: JSON.stringify({angle_id: angleId})}),
  storyboard: (id: string) => api<Storyboard>(`/projects/${id}/storyboard`),
  saveStoryboard: (id: string, board: Storyboard) =>
    api<Storyboard>(`/projects/${id}/storyboard`, {
      method: "PUT",
      body: JSON.stringify({
        revision: board.revision,
        target_platform: board.target_platform,
        style: board.style,
        speech_voice: board.speech_voice,
        scenes: board.scenes,
      }),
    }),
  approve: (id: string, overrideBudget = false) =>
    api(`/projects/${id}/storyboard/approve`, {
      method: "POST",
      body: JSON.stringify({override_budget: overrideBudget}),
    }),
  regenerate: (projectId: string, sceneId: string, target: string, instruction = "") =>
    api(`/projects/${projectId}/scenes/${sceneId}/regenerate`, {
      method: "POST",
      body: JSON.stringify({target, instruction}),
    }),
  uploadImage: (projectId: string, sceneId: string, file: File) => {
    const body = new FormData();
    body.set("file", file);
    return api(`/projects/${projectId}/scenes/${sceneId}/image`, {method: "POST", body});
  },
  uploadMusic: (projectId: string, file: File) => {
    const body = new FormData();
    body.set("file", file);
    body.set("rights_attested", "true");
    return api(`/projects/${projectId}/music`, {method: "POST", body});
  },
  exports: async (id: string) =>
    (await api<{items: ExportItem[]}>(`/projects/${id}/exports`)).items,
};

export function humanError(error: unknown): string {
  if (!(error instanceof ApiError)) return error instanceof Error ? error.message : "发生未知错误";
  if (typeof error.detail === "string") return error.detail;
  if (error.detail && typeof error.detail === "object") {
    const detail = error.detail as {message?: string; errors?: string[]};
    return [detail.message, ...(detail.errors ?? [])].filter(Boolean).join("\n");
  }
  return error.message;
}
