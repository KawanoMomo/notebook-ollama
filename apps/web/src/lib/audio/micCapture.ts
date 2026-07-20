/** getUserMedia + ScriptProcessorNode による PCM キャプチャ(spec 決定 #3)。
 *
 * AudioWorklet が理想だが別ファイル配信が必要になるため、v1 は
 * ScriptProcessorNode(deprecated だが全ブラウザ動作)で完結させる。
 * ローカルアプリ用途ではレイテンシ要件も満たす。tech-debt として v2 検討。
 */

export interface MicCapture {
  stop(): void;
}

export async function startMicCapture(
  onChunk: (samples: Float32Array, sampleRate: number) => void,
): Promise<MicCapture> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  });
  const ctx = new AudioContext();
  const source = ctx.createMediaStreamSource(stream);
  const proc = ctx.createScriptProcessor(4096, 1, 1);
  proc.onaudioprocess = (ev) => {
    // getChannelData のバッファは ScriptProcessorNode によって再利用されるため、
    // 呼び出し先(VAD 等)が非同期に保持できるよう必ずコピーしてから渡す。
    // このコピーは所有権の生成点であり、削除すると VAD の参照保持契約が壊れる。
    onChunk(ev.inputBuffer.getChannelData(0).slice(), ctx.sampleRate);
  };
  source.connect(proc);
  proc.connect(ctx.destination);
  return {
    stop() {
      proc.disconnect();
      source.disconnect();
      for (const t of stream.getTracks()) t.stop();
      void ctx.close();
    },
  };
}
