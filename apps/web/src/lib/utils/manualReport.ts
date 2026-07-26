/**
 * 手動レポート(backend の crash-pending に存在しない PendingCrash)の
 * タイトル/本文を組み立てる純粋関数群。
 *
 * 背景(実機FB 2026-07-26): 取り込み失敗のように「捕捉済みで UI に出るエラー」は
 * クラッシュレポートの捕捉対象外(未捕捉例外・プロセスクラッシュのみ)なので、
 * ユーザーが目にしたエラーを報告する手段が「空フォームに全部手入力」しかなかった。
 * 失敗したソースから内容を組み立てて事前入力する。
 */
import type { PendingCrash, Source } from '$lib/api/types';

/** 手動レポートの id 接頭辞。CrashPreviewDialog が backend 往復をスキップする印。 */
export const MANUAL_ID_PREFIX = 'manual-';

/**
 * 失敗したソースから報告用の PendingCrash を組み立てる。
 * `nowIso` / `idSuffix` は決定的なテストのために注入可能にしている。
 */
export function buildSourceErrorCrash(
  source: Source,
  opts: { nowIso?: string; idSuffix?: string } = {},
): PendingCrash {
  const nowIso = opts.nowIso ?? new Date().toISOString();
  const idSuffix = opts.idSuffix ?? String(Date.now());
  return {
    id: `${MANUAL_ID_PREFIX}${idSuffix}`,
    fingerprint: '',
    created_at: nowIso,
    exception_type: 'IngestionError',
    exception_message: source.error_msg ?? '取り込みに失敗しました',
    trace: [],
    hardware: {},
    // ソース本文やチャンクは載せない(spec のホワイトリスト方針どおり、
    // 収集するのは種別・拡張子・エラー文言といったメタ情報のみ)。
    log_tail: [
      {
        event_name: 'source_ingestion_failed',
        source_kind: source.kind,
        file_extension: fileExtension(source.origin),
        status: source.status,
      },
    ],
    source: 'frontend',
  };
}

/** origin から拡張子だけを取り出す(ファイル名そのものは載せない)。 */
function fileExtension(origin: string | null | undefined): string {
  if (!origin) return '';
  const dot = origin.lastIndexOf('.');
  return dot >= 0 ? origin.slice(dot).toLowerCase() : '';
}

/**
 * 手動レポートの初期タイトル/本文。内容が無い場合(「+ 新規報告を作成」の
 * 空フォーム)は両方とも空文字を返し、従来どおり白紙で開く。
 */
export function buildManualPrefill(crash: PendingCrash): { title: string; body: string } {
  if (!crash.exception_type && !crash.exception_message) {
    return { title: '', body: '' };
  }
  const message = crash.exception_message || '(メッセージなし)';
  const title = crash.exception_type ? `[${crash.exception_type}] ${message}` : message;

  const lines = ['## 発生した事象', '', message, ''];
  const context = crash.log_tail[0];
  if (context) {
    lines.push('## 状況', '');
    for (const [key, value] of Object.entries(context)) {
      if (value === '' || value === null || value === undefined) continue;
      lines.push(`- ${key}: ${String(value)}`);
    }
    lines.push('');
  }
  lines.push('## 補足', '', '(再現手順や期待した動作があれば追記してください)');
  return { title, body: lines.join('\n') };
}
