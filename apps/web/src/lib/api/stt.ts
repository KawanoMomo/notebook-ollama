import { request } from './client';

export interface TranscribeResult {
  text: string;
  duration_ms: number;
}

export const sttApi = {
  /** 音声 blob(基本は 16kHz mono WAV)をローカル Whisper で認識する。 */
  transcribe(blob: Blob): Promise<TranscribeResult> {
    const form = new FormData();
    form.append('file', blob, 'voice.wav');
    return request<TranscribeResult>('/api/stt/transcribe', {
      method: 'POST',
      body: form,
    });
  },
};
