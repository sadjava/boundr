export type VideoStatus =
  | "UPLOADING"
  | "UPLOADED"
  | "QUEUED"
  | "PROCESSING"
  | "COMPLETED"
  | "FAILED";

export type JobStatus = "QUEUED" | "PROCESSING" | "COMPLETED" | "FAILED";

export interface User {
  id: string;
  email: string;
  name: string;
  created_at: string;
}

export interface Project {
  id: string;
  user_id: string;
  name: string;
  description: string | null;
  action_types: string[];
  objects: string[];
  created_at: string;
  updated_at: string;
}

export interface Job {
  id: string;
  video_id: string;
  pipeline: string;
  status: JobStatus;
  created_at: string;
  started_at: string | null;
  updated_at: string;
  error_msg: string | null;
}

export interface Task {
  id: string;
  project_id: string;
  name: string;
  video_count: number;
  annotated_count: number;
  created_at: string;
  updated_at: string;
}

export type FineTuneStatus = "QUEUED" | "PROCESSING" | "COMPLETED" | "FAILED";

export interface FineTune {
  id: string;
  user_id: string;
  project_id: string | null;
  name: string;
  display_name: string;
  status: FineTuneStatus;
  error_msg: string | null;
  s3_prefix: string;
  task_ids: string[];
  manifest: Record<string, unknown> | null;
  created_at: string;
  started_at: string | null;
  updated_at: string;
}

export interface Video {
  id: string;
  project_id: string;
  task_id: string;
  name: string;
  s3_key: string;
  status: VideoStatus;
  duration: number | null;
  created_at: string;
  updated_at: string;
  upload_url?: string | null;
  playback_url?: string | null;
  latest_job?: Job | null;
  prev_video_id?: string | null;
  next_video_id?: string | null;
}

export interface AnnotationSegment {
  id: string;
  start: number;
  end: number;
  action: string;
  object: string | null;
  keyframe: number;
}

export interface AnnotationData {
  video_id: string;
  duration: number;
  fps?: number | null;
  segments: AnnotationSegment[];
}

export interface Annotation {
  id: string;
  video_id: string;
  s3_key: string | null;
  data: AnnotationData;
  version: number;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface InferenceType {
  id: string;
  name: string;
  description: string;
}

export const INFERENCE_TYPES: InferenceType[] = [
  { id: "marlin", name: "Marlin 2B", description: "GPU video captioning through llama.cpp" },
  { id: "marlin_gpt", name: "Marlin 2B + GPT", description: "Marlin captions mapped to actions by GPT-4o-mini" },
  { id: "overlap", name: "Overlap", description: "Concurrent actions that overlap in time" },
  { id: "sequential", name: "Sequential", description: "Non-overlapping actions, one after another" },
  { id: "dense", name: "Dense", description: "Shorter windows with more overlap" },
  { id: "pegasus_analyze", name: "Pegasus (analyze)", description: "TwelveLabs Pegasus, free-form actions via a JSON schema" },
  { id: "pegasus_segment", name: "Pegasus (segment)", description: "TwelveLabs Pegasus, time-based segmentation of actions" },
];
