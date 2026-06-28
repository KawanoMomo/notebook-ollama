"""tests for core.crash_reporter.reported_store.

spec §9: 同一 fingerprint の crash を 2 回ユーザに promptしないための、
ローカル送信済みリストの I/O。`data_dir/reported.txt` (UTF-8、1行 1 fingerprint)。
"""
from __future__ import annotations

import pytest

from core.crash_reporter import reported_store
from core.crash_reporter.reported_store import (
    count,
    is_reported,
    mark_reported,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """テスト間でモジュール内キャッシュをクリア。"""
    reported_store._CACHE.clear()
    yield
    reported_store._CACHE.clear()


# --- 基本挙動 -----------------------------------------------------------------


def test_missing_file_returns_false_for_is_reported(tmp_path):
    assert not is_reported(tmp_path, "any-fingerprint")


def test_missing_file_count_zero(tmp_path):
    assert count(tmp_path) == 0


def test_missing_file_does_not_create_anything(tmp_path):
    """未送信判定だけでファイルが勝手に作られないこと (副作用最小化)。"""
    _ = is_reported(tmp_path, "abc")
    _ = count(tmp_path)
    assert not (tmp_path / "reported.txt").exists()


def test_mark_then_is_reported(tmp_path):
    assert not is_reported(tmp_path, "abc")
    mark_reported(tmp_path, "abc")
    assert is_reported(tmp_path, "abc")


def test_mark_idempotent_no_op_on_duplicate(tmp_path):
    """同じ fingerprint を複数回 mark しても 1 行しか書かれない。"""
    mark_reported(tmp_path, "abc")
    mark_reported(tmp_path, "abc")
    mark_reported(tmp_path, "abc")
    assert count(tmp_path) == 1
    content = (tmp_path / "reported.txt").read_text(encoding="utf-8")
    # ちょうど 1 行 = "abc\n"
    assert content == "abc\n"


def test_multiple_distinct_fingerprints(tmp_path):
    for fp in ["aaa", "bbb", "ccc"]:
        mark_reported(tmp_path, fp)
    assert count(tmp_path) == 3
    for fp in ["aaa", "bbb", "ccc"]:
        assert is_reported(tmp_path, fp)


# --- 永続性 -------------------------------------------------------------------


def test_persists_across_cache_clear(tmp_path):
    """プロセス再起動相当 (cache 空) でも disk から復元できる。"""
    mark_reported(tmp_path, "abc")
    reported_store._CACHE.clear()
    assert is_reported(tmp_path, "abc")
    assert count(tmp_path) == 1


def test_existing_content_preserved_on_new_append(tmp_path):
    """既存ファイルの中身を壊さず追記される (atomic write の retain)。"""
    (tmp_path / "reported.txt").write_text("aaa\nbbb\n", encoding="utf-8")
    mark_reported(tmp_path, "ccc")
    content = (tmp_path / "reported.txt").read_text(encoding="utf-8")
    assert "aaa" in content
    assert "bbb" in content
    assert "ccc" in content
    assert count(tmp_path) == 3


def test_creates_parent_dir_if_missing(tmp_path):
    """data_dir が未作成でも mark_reported は自動で親ディレクトリを作る。"""
    nested = tmp_path / "does" / "not" / "exist"
    mark_reported(nested, "abc")
    assert (nested / "reported.txt").exists()
    assert is_reported(nested, "abc")


# --- 入力エッジケース ---------------------------------------------------------


def test_empty_file_handled_gracefully(tmp_path):
    (tmp_path / "reported.txt").write_text("", encoding="utf-8")
    assert not is_reported(tmp_path, "abc")
    assert count(tmp_path) == 0


def test_file_with_blank_lines_ignored(tmp_path):
    """空行や前後 whitespace は読み込み時に無視。"""
    (tmp_path / "reported.txt").write_text(
        "\n\nabc\n\n\nxyz\n\n", encoding="utf-8"
    )
    assert is_reported(tmp_path, "abc")
    assert is_reported(tmp_path, "xyz")
    assert count(tmp_path) == 2


def test_file_with_trailing_whitespace_stripped(tmp_path):
    (tmp_path / "reported.txt").write_text("abc  \n", encoding="utf-8")
    assert is_reported(tmp_path, "abc")
    assert not is_reported(tmp_path, "abc  ")


def test_does_not_match_substring(tmp_path):
    mark_reported(tmp_path, "abcdef")
    assert not is_reported(tmp_path, "abc")
    assert not is_reported(tmp_path, "def")
    assert not is_reported(tmp_path, "abcdef ")
    assert not is_reported(tmp_path, " abcdef")


# --- エンコーディング / 文字種網羅 -------------------------------------------


@pytest.mark.parametrize(
    "fp",
    [
        "a" * 40,  # 典型的な SHA1 hex
        "0123456789abcdef" * 2 + "01234567",
        "x",  # 短い
        "long_" + "x" * 200,  # 非常に長い
        "日本語fp",  # CJK
        "𩸽𠮷",  # サロゲートペア (BMP外)
        "with-special_chars.123",
        "tab\tinside",  # タブ
    ],
)
def test_mark_and_lookup_various_fingerprints(tmp_path, fp):
    assert not is_reported(tmp_path, fp)
    mark_reported(tmp_path, fp)
    assert is_reported(tmp_path, fp)


def test_utf8_encoded_correctly_on_disk(tmp_path):
    mark_reported(tmp_path, "日本語fp")
    raw = (tmp_path / "reported.txt").read_bytes()
    assert "日本語fp".encode() in raw


def test_utf8_surrogate_pair_roundtrip(tmp_path):
    """BMP 外 (寿司・𩸽 など) も保持。"""
    mark_reported(tmp_path, "𩸽")
    reported_store._CACHE.clear()  # disk 経由で復元
    assert is_reported(tmp_path, "𩸽")


# --- キャッシュ挙動 -----------------------------------------------------------


def test_is_reported_uses_in_memory_cache_after_first_load(tmp_path):
    """is_reported は最初の load 後ファイルを再読み込みしない (O(1) cache)。

    実装契約: mark_reported 経由でしか set が変わらない。外部から file が
    書き換えられても、同一プロセスの cache はそれを取り込まない。
    """
    mark_reported(tmp_path, "abc")
    # ファイル内容を外部から書き換える (テスト用)
    (tmp_path / "reported.txt").write_text("def\n", encoding="utf-8")
    # cache は "abc" を保持しているはず
    assert is_reported(tmp_path, "abc")
    # "def" は cache に無いので False
    assert not is_reported(tmp_path, "def")


def test_count_consistent_with_is_reported(tmp_path):
    for fp in [f"fp_{i:03d}" for i in range(50)]:
        mark_reported(tmp_path, fp)
    assert count(tmp_path) == 50
    for fp in [f"fp_{i:03d}" for i in range(50)]:
        assert is_reported(tmp_path, fp)


# --- 異常入力からの復旧 -------------------------------------------------------


def test_handles_existing_file_with_crlf_line_endings(tmp_path):
    """Windows で生成された CRLF 行も読める (strip で吸収)。"""
    (tmp_path / "reported.txt").write_bytes(b"abc\r\nxyz\r\n")
    assert is_reported(tmp_path, "abc")
    assert is_reported(tmp_path, "xyz")
    assert count(tmp_path) == 2


# --- 回帰: 末尾改行なしファイルへの append が連結を起こさない (HIGH) -----------


def test_append_to_file_without_trailing_newline_lf(tmp_path):
    """既存ファイルが末尾 \\n 無しでも、追記が前行と連結されない (spec §9 死守)。

    realistic シナリオ: 外部 GUI editor の strip-trailing-newline、手編集、
    あるいは partial-write された reported.txt。
    pre-seed: `b"hash_1\\nhash_2"` (no trailing newline)
    → mark_reported("hash_3") 後、cache を clear して disk から復元しても
       hash_1 / hash_2 / hash_3 すべて独立に存在し、`hash_2hash_3` という
       連結文字列は存在しないこと。
    """
    (tmp_path / "reported.txt").write_bytes(b"hash_1\nhash_2")
    mark_reported(tmp_path, "hash_3")
    reported_store._CACHE.clear()
    assert is_reported(tmp_path, "hash_1")
    assert is_reported(tmp_path, "hash_2")
    assert is_reported(tmp_path, "hash_3")
    assert not is_reported(tmp_path, "hash_2hash_3")
    assert count(tmp_path) == 3


def test_append_to_file_without_trailing_newline_crlf(tmp_path):
    """Windows CRLF 版: `b"hash_1\\r\\nhash_2"` (末尾 \\r\\n 無し)。"""
    (tmp_path / "reported.txt").write_bytes(b"hash_1\r\nhash_2")
    mark_reported(tmp_path, "hash_3")
    reported_store._CACHE.clear()
    assert is_reported(tmp_path, "hash_1")
    assert is_reported(tmp_path, "hash_2")
    assert is_reported(tmp_path, "hash_3")
    assert not is_reported(tmp_path, "hash_2hash_3")
    assert count(tmp_path) == 3


# --- 防御的検証: 不正 fingerprint は ValueError -------------------------------


def test_mark_reported_rejects_embedded_newline(tmp_path):
    """fingerprint 内に \\n を含めば 2 行書かれてファイル破壊 → 早期拒否。"""
    with pytest.raises(ValueError):
        mark_reported(tmp_path, "abc\ndef")


def test_mark_reported_rejects_embedded_carriage_return(tmp_path):
    """\\r も同様 (Windows EOL の片割れ)。"""
    with pytest.raises(ValueError):
        mark_reported(tmp_path, "abc\rdef")


def test_mark_reported_rejects_leading_whitespace(tmp_path):
    """前後 whitespace は読み込み時 strip されるので、書き込み時に拒否する
    (asymmetry によるサイレント de-dup ミスを防ぐ)。"""
    with pytest.raises(ValueError):
        mark_reported(tmp_path, " abc")


def test_mark_reported_rejects_trailing_whitespace(tmp_path):
    with pytest.raises(ValueError):
        mark_reported(tmp_path, "abc ")


# --- portability: text-mode の \\n → \\r\\n 変換を抑止 ------------------------


def test_writes_lf_only_regardless_of_platform(tmp_path):
    """`newline=""` で open することで、Windows 上でも \\n が \\r\\n に
    変換されない (line-ending policy: LF-only)。

    既存ファイルが無い状態から mark_reported を 2 回呼び、bytes として読み
    込んで \\r\\n が現れないことを確認する。
    """
    mark_reported(tmp_path, "abc")
    mark_reported(tmp_path, "xyz")
    raw = (tmp_path / "reported.txt").read_bytes()
    assert b"\r\n" not in raw
    assert raw == b"abc\nxyz\n"
