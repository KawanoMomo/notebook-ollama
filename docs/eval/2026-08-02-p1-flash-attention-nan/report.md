# P1 検証レポート: bge-m3 GPU embedding の NaN 再現確認(OLLAMA_FLASH_ATTENTION)

- 日付: 2026-08-02(レポート整理: 2026-08-03)
- 起票元: spec `2026-06-28-igpu-npu-acceleration-design.md` addendum K4 / P-1
- 関連: ADR-018、Ollama upstream [#13572](https://github.com/ollama/ollama/issues/13572)(closed, 根本未修正)/ [#14657](https://github.com/ollama/ollama/issues/14657) / [#16625](https://github.com/ollama/ollama/issues/16625)

## 目的

現行の `embedding_options={"num_gpu": 0}`(CPU 強制)は bge-m3 GPU 経路の NaN バグ回避。
addendum K4 で新回避策候補 `OLLAMA_FLASH_ATTENTION=false` が浮上したため、開発機で
(1) NaN が再現するか、(2) flash attention 無効化で挙動が変わるか、(3) GPU 化の速度便益、
を実測する。

## 方法

- 環境: RTX 2080 Ti / Ollama **0.32.1** / bge-m3:latest (F16)
- **本番 Ollama(11434)には触れず**、`OLLAMA_HOST=127.0.0.1:11500` の隔離 `ollama serve` を
  環境変数を変えて起動し直して比較(モデルストアは共有・読み取りのみ)
- 入力 14 ケース: upstream 再現条件を模した日本語長文(274〜8,220字)・空白なし日本語連続・
  長い英文(#14657 相当)・チェコ語ダイアクリティクス+句読点(#16625 相当)・高密度記号列・日英混在
- 判定: `/api/embeddings` 応答の NaN/Inf 数、ゼロベクトル、HTTP エラー。`/api/ps` の
  `size_vram` でモデルが実際に GPU に載っていることを確認
- スクリプト: セッション scratchpad `p1_nan_probe.py`(使い捨て)

## 結果

| 構成 | GPU載り (size_vram) | NaN/Inf/ゼロベクトル | 平均応答 | 備考 |
|---|---|---|---|---|
| A: FA=true + GPU | 100% | **0 件** | 439ms 相当※ | ※初回ロード13.8秒を除く10ケース平均 約385ms |
| B: FA=false + GPU | 100% | **0 件** | 439.5ms | |
| C: CPU (num_gpu=0) | 0%(CPU) | **0 件** | 1668.2ms | 現行構成の参照値 |

- 全構成共通で 3 ケース(jp-30x / en-40x / cz-punct-40x)が
  `the input length exceeds the context length` の **明示 HTTP 500** で拒否された。
  これは NaN ではなく正常なコンテキスト長ガード(0.32 系の挙動)
- ベクトルノルムは全構成で 24〜26 の正常域、構成間で数値もほぼ一致

## 結論

1. **Ollama 0.32.1 + 本コーパスでは GPU 経路の NaN は再現しなかった**(FA の on/off に依らず)
2. **`num_gpu=0` の CPU ピンは当面維持する**(spec R4 のまま)。理由:
   - 負の再現結果は「このコーパスで出なかった」ことしか証明しない。upstream #14657 は
     **同型 GPU(RTX 2080 Ti)** での再現報告で、トリガは入力依存(特定トークン列)
   - 現行運用で CPU 埋め込みの速度は実用上のボトルネックになっていない
3. ただし **GPU 化の便益は約 3.8 倍**(439.5ms vs 1668.2ms)と確認できた。切替を検討する
   場合の次のステップは「実ノートブックの全チャンクを GPU で再埋め込みし、NaN 検知
   (PR #13599 のバリデーション)が 1 件も出ないことを確認するカナリア運用」。この判断は
   モデル切替=再インデックスの既知制限と合わせて別途行う

## 記録

- 検証データ取得完了直後の 2026-08-02 20:18 に開発機が bugcheck 0x00020001
  (HYPERVISOR_ERROR)で再起動した。本検証の負荷(埋め込み14件×3構成)は軽微であり
  直接原因の可能性は低いが、時間帯が重なるため記録しておく。git・検証データへの実害なし
