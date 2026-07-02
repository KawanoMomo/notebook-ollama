"""送信済み crash fingerprint のローカル永続化 (重複 Issue 抑制用)。

spec §9: 同一 fingerprint を Issue 化したら以後ユーザに promptしない。

ファイル形式: `data_dir/reported.txt`、UTF-8、1 行 1 fingerprint、LF 区切り。
- 読み込み: 末尾 / 前後 whitespace と空行は無視。CRLF (Windows) も透過的に扱う。
- 書き込み: `open(..., newline="")` で LF-only を強制 (text-mode の
  `\\n` → `\\r\\n` 自動変換を抑止) し、append 前に既存ファイルの末尾改行を
  保証する。これにより外部編集等で末尾改行が落ちていても前行との連結を防ぐ
  (前行・新規行両方が dedup set から消えて再 prompt される事故を回避)。
- `mark_reported` は不正 fingerprint (改行・前後 whitespace) を ValueError
  で早期拒否する (ファイル破壊や非対称な dedup を防ぐ)。
- `is_reported` は in-memory set cache で O(1) 判定。
- `mark_reported` は冪等。既に登録済みなら no-op、新規なら append + fsync。
"""
from __future__ import annotations

import os
from pathlib import Path

_FILE_NAME = "reported.txt"

# プロセス内キャッシュ: 解決済み絶対 data_dir → 登録済み fingerprint set。
# is_reported を O(1) にし、毎回 disk スキャンを避ける。
# mark_reported は新規追加時のみ disk と cache を両方更新する。
_CACHE: dict[str, set[str]] = {}


def _file_path(data_dir: Path) -> Path:
    return Path(data_dir) / _FILE_NAME


def _cache_key(data_dir: Path) -> str:
    # 絶対パス文字列で safely 区別。data_dir が未作成でも resolve() は動く。
    return str(Path(data_dir).resolve())


def _load(data_dir: Path) -> set[str]:
    """data_dir に対応する set を返す。初回はファイルから復元。"""
    key = _cache_key(data_dir)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    s: set[str] = set()
    path = _file_path(data_dir)
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                for raw_line in f:
                    fp = raw_line.strip()
                    if fp:
                        s.add(fp)
        except OSError:
            # 読み込み失敗は黙って空セット扱い (起動を止めない)。
            pass
    _CACHE[key] = s
    return s


def is_reported(data_dir: Path, fingerprint: str) -> bool:
    """既に Issue 起票済みの fingerprint かを O(1) で判定する。"""
    return fingerprint in _load(data_dir)


def mark_reported(data_dir: Path, fingerprint: str) -> None:
    """fingerprint を「送信済み」として記録する (冪等)。

    - 不正 fingerprint (改行を含む / 前後 whitespace あり) は ValueError。
    - 既存に含まれていれば no-op (ファイルは触らない)。
    - 新規なら親ディレクトリを作成し append + fsync で確実に flush。
    - 既存ファイル末尾に改行が無ければ自動で補ってから新行を append する
      (前行と連結して dedup set から消える事故を防ぐ)。
    - text-mode の `\\n` → `\\r\\n` 自動変換は `newline=""` で抑止し
      LF-only を強制する (Windows / Unix 共通の確定的フォーマット)。
    """
    # 防御的検証: 不正な fingerprint を即拒否。
    # 改行が混入していると 1 行を超えて書き込まれファイルが破壊される。
    # 前後 whitespace があると _load 側の strip と非対称になり、
    # mark → is_reported の往復で False が返るサイレント不整合を生む。
    if not isinstance(fingerprint, str):
        raise ValueError("fingerprint must be a string")
    if "\n" in fingerprint or "\r" in fingerprint:
        raise ValueError(
            "fingerprint must not contain newline characters: "
            f"{fingerprint!r}"
        )
    if fingerprint.strip() != fingerprint:
        raise ValueError(
            "fingerprint must not have leading/trailing whitespace: "
            f"{fingerprint!r}"
        )
    if fingerprint == "":
        raise ValueError("fingerprint must not be empty")

    s = _load(data_dir)
    if fingerprint in s:
        return  # 冪等: 重複登録 no-op
    path = _file_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    # 末尾改行保証: 既存ファイルが末尾改行で終わっていなければ補う。
    # 想定シナリオ: 外部 GUI editor の strip-trailing-newline、手編集、
    # 旧コードによる partial write など。これを怠ると新規 fingerprint が
    # 前行と連結し、両方が dedup set から消えてユーザが同じ crash で
    # 再 prompt される (spec §9 違反)。
    needs_leading_newline = False
    if path.exists():
        try:
            with path.open("rb") as rf:
                # ファイル末尾 1 バイトだけ確認 (大ファイル対策で seek)。
                rf.seek(0, os.SEEK_END)
                size = rf.tell()
                if size > 0:
                    rf.seek(-1, os.SEEK_END)
                    last = rf.read(1)
                    if last not in (b"\n", b"\r"):
                        needs_leading_newline = True
        except OSError:
            # 読み取り失敗時は安全側 (改行補完あり) に倒す。
            needs_leading_newline = True

    # newline="" で text-mode の自動 EOL 変換を抑止し LF-only を保証。
    with path.open("a", encoding="utf-8", newline="") as f:
        if needs_leading_newline:
            f.write("\n")
        f.write(fingerprint + "\n")
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            # fsync 不可なファイルシステム (一部の network FS) では諦める。
            pass
    s.add(fingerprint)


def count(data_dir: Path) -> int:
    """登録されている送信済み fingerprint 数を返す。"""
    return len(_load(data_dir))
