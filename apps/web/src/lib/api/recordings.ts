import { request } from './client';

export interface RecordingStarted {
  recording_id: string;
  source_id: string;
  status: string;
  live_caption: boolean;
}

export interface RecordingStopped {
  recording_id: string;
  source_id: string;
  status: string;
  paths: Record<string, string | null>;
}

export interface LiveGainResult {
  ok: boolean;
  mic_db: number;
  sys_db: number;
}

export interface AudioDevice {
  index: number;
  name: string;
  max_channels: number;
  default_sample_rate: number;
  is_loopback: boolean;
}

export interface StartOptions {
  live_caption: boolean;
  mic_device_index?: number | null;
  system_device_index?: number | null;
}

export const recordingsApi = {
  start: (notebookId: string, opts: StartOptions) =>
    request<RecordingStarted>(`/api/notebooks/${notebookId}/recordings`, {
      method: 'POST',
      body: JSON.stringify(opts),
    }),
  stop: (notebookId: string, rid: string) =>
    request<RecordingStopped>(
      `/api/notebooks/${notebookId}/recordings/${rid}/stop`,
      { method: 'POST' },
    ),
  setGain: (notebookId: string, rid: string, mic_db: number, sys_db: number) =>
    request<LiveGainResult>(
      `/api/notebooks/${notebookId}/recordings/${rid}/live-gain`,
      {
        method: 'PUT',
        body: JSON.stringify({ mic_db, sys_db }),
      },
    ),
  devices: () => request<AudioDevice[]>(`/api/audio-devices`),
};
