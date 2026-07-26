/**
 * 手動レポートの組み立て(実機FB 2026-07-26)。
 *
 * 取り込み失敗のような「捕捉済みで UI に出るエラー」はクラッシュレポートの
 * 自動収集対象外(未捕捉例外・プロセスクラッシュのみ)なので、ユーザーが
 * 報告するには空フォームへの全手入力しかなかった。失敗したソースから
 * 事前入力する経路を検証する。
 */
import { describe, expect, it } from 'vitest';
import {
  MANUAL_ID_PREFIX,
  buildManualPrefill,
  buildSourceErrorCrash,
} from '$lib/utils/manualReport';
import type { PendingCrash, Source } from '$lib/api/types';

function failedSource(overrides: Partial<Source> = {}): Source {
  return {
    id: 'src1',
    notebook_id: 'nb1',
    kind: 'pdf',
    title: null,
    origin: 'baystarscurry202009.pdf',
    status: 'error',
    error_msg: 'このPDFは全ページが画像で、OCRでも文字を読み取れませんでした',
    error_remediation: '別のツールでOCRしてから取り込んでください。',
    bytes: null,
    page_count: null,
    chunk_count: null,
    created_at: 't',
    updated_at: 't',
    ...overrides,
  };
}

describe('buildSourceErrorCrash', () => {
  it('CrashPreviewDialog が backend 往復をスキップする manual- id を付ける', () => {
    const crash = buildSourceErrorCrash(failedSource(), { idSuffix: '1' });
    expect(crash.id.startsWith(MANUAL_ID_PREFIX)).toBe(true);
    expect(crash.source).toBe('frontend');
  });

  it('エラー本文を exception_message に載せる', () => {
    const crash = buildSourceErrorCrash(failedSource(), { idSuffix: '1' });
    expect(crash.exception_message).toContain('読み取れませんでした');
    expect(crash.exception_type).toBe('IngestionError');
  });

  it('ファイル名は載せず拡張子だけを載せる (収集はメタ情報のみ)', () => {
    const crash = buildSourceErrorCrash(failedSource(), { idSuffix: '1' });
    const context = crash.log_tail[0];
    expect(context.file_extension).toBe('.pdf');
    expect(JSON.stringify(crash)).not.toContain('baystarscurry');
  });

  it('error_msg が無くても既定文で組み立てる', () => {
    const crash = buildSourceErrorCrash(failedSource({ error_msg: null }), { idSuffix: '1' });
    expect(crash.exception_message).toBe('取り込みに失敗しました');
  });
});

describe('buildManualPrefill', () => {
  function blankCrash(overrides: Partial<PendingCrash> = {}): PendingCrash {
    return {
      id: 'manual-1',
      fingerprint: '',
      created_at: 't',
      exception_type: '',
      exception_message: '',
      trace: [],
      hardware: {},
      log_tail: [],
      source: 'frontend',
      ...overrides,
    };
  }

  it('「+ 新規報告を作成」の空 crash は白紙のまま (従来挙動を維持)', () => {
    expect(buildManualPrefill(blankCrash())).toEqual({ title: '', body: '' });
  });

  it('内容を持つ crash はタイトルと本文を組み立てる', () => {
    const crash = buildSourceErrorCrash(failedSource(), { idSuffix: '1' });
    const { title, body } = buildManualPrefill(crash);
    expect(title).toBe('[IngestionError] このPDFは全ページが画像で、OCRでも文字を読み取れませんでした');
    expect(body).toContain('## 発生した事象');
    expect(body).toContain('読み取れませんでした');
    expect(body).toContain('file_extension: .pdf');
    expect(body).toContain('## 補足');
  });

  it('空の値は状況セクションに出さない', () => {
    const crash = buildSourceErrorCrash(failedSource({ origin: null }), { idSuffix: '1' });
    expect(buildManualPrefill(crash).body).not.toContain('file_extension:');
  });
});
