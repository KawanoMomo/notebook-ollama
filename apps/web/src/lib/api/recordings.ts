import { request } from './client';
import type { ActiveRecording } from './types';

export interface RecordingStarted {
  recording_id: string;
  source_id: string;
  status: string;
  live_caption: boolean;
  /** 発表モード: セッションに紐づいたスライドソース ID(通常録音は null)。 */
  presentation_source_id?: string | null;
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
  /** 発表モード: 発表対象スライドソース(kind pdf/pptx)。同一NB内で backend が検証する。 */
  presentation_source_id?: string;
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
  /** 録音タイムラインへの汎用マーカー記録(発表モードの page マーカー等、spec §6)。 */
  postMarker: (notebookId: string, rid: string, kind: string, value: string) =>
    request<{ at_ms: number }>(
      `/api/notebooks/${notebookId}/recordings/${rid}/markers`,
      {
        method: 'POST',
        body: JSON.stringify({ kind, value }),
      },
    ),
  /**
   * 進行中の録音セッション照会(リロード復帰用、spec §6 中断・異常系)。
   * セッションが無ければ backend は 204 を返し、`client.ts` の `request<T>` が
   * `undefined` を返す。
   */
  getActive: (notebookId: string) =>
    request<ActiveRecording | undefined>(
      `/api/notebooks/${notebookId}/recordings/active`,
    ),
};
