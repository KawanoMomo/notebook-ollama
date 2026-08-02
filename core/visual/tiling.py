"""ページPNGのタイル分割 (Stage 4, spec §6)。

視覚埋め込みはモデル側で入力を固定解像度へ縮小するため、A4 1ページを1枚のまま
埋め込むと細かい図表・表の文字が潰れる。ページを rows x cols のタイルに分けて
タイル単位で埋め込むと局所の情報が残る。タイル境界をまたぐ図が両側で切れるのを
防ぐため、各タイルは overlap 分だけ隣へはみ出して切り出す。

Pillow は pyproject 上は visual extra に列挙されているが、実際には base 依存の
python-pptx が無条件に要求するため extra 無しの環境にも必ず入っている
(uv.lock: python-pptx -> pillow)。それでも encoder._TransformersBackend.
embed_image と同じく関数内 import に揃えておく: core/ 配下で重い/オプショナルな
ライブラリを遅延 import するのが本リポジトリの既存規約で、将来 python-pptx を
外しても import 時点では壊れない。
"""
from __future__ import annotations

import io
from dataclasses import dataclass

# タイルの基準サイズがこれ未満になる分割は行わない。極小タイルは視覚埋め込みの
# 入力としてノイズにしかならず、タイル数だけが増えて構築時間を食うため。
MIN_TILE_PX = 32

# crop 結果をそのまま PNG 保存できるモード。pymupdf の tobytes("png") は RGB /
# RGBA を返すので通常はここに入る。CMYK など PNG 非対応モードだけ RGB へ変換する。
_PNG_SAFE_MODES = frozenset({"1", "L", "LA", "P", "PA", "RGB", "RGBA", "I", "I;16"})


@dataclass(frozen=True)
class Tile:
    """分割後の1タイル。

    index : 左上から行優先 (row-major) の通し番号。0 始まり。
    row/col : グリッド上の位置。0 始まり。
    box  : 元画像ピクセル座標の (left, top, right, bottom)。overlap 込み、
           画像境界でクリップ済み。right/bottom は排他 (PIL の crop と同じ)。
    png  : このタイルの PNG バイト列。
    """

    index: int
    row: int
    col: int
    box: tuple[int, int, int, int]
    png: bytes

    @property
    def width(self) -> int:
        return self.box[2] - self.box[0]

    @property
    def height(self) -> int:
        return self.box[3] - self.box[1]


def split_tiles(png: bytes, *, rows: int, cols: int, overlap: float) -> list[Tile]:
    """PNG バイト列を rows x cols のタイルへ分割する純関数。

    - タイルは左上から行優先で index=0.. を割り当てる
    - 基準サイズは (W // cols, H // rows)。端数ピクセルは最終行・最終列へ寄せる
    - 各タイルは overlap x 基準辺長 だけ上下左右へ広げ、画像境界でクリップする
      (水平方向は基準幅、垂直方向は基準高さを基準辺長とする)
    - rows == cols == 1、または基準サイズが MIN_TILE_PX 未満になる場合は分割せず、
      元の PNG バイト列をそのまま index=0 の1枚として返す (再エンコードしない)

    Raises:
        ValueError: rows/cols が 1 未満、または overlap が負のとき。
    """
    if rows < 1 or cols < 1:
        raise ValueError(f"rows/cols must be >= 1 (got rows={rows}, cols={cols})")
    if overlap < 0:
        raise ValueError(f"overlap must be >= 0 (got {overlap})")

    from PIL import Image

    with Image.open(io.BytesIO(png)) as im:
        width, height = im.size
        base_w = width // cols
        base_h = height // rows

        if (rows == 1 and cols == 1) or base_w < MIN_TILE_PX or base_h < MIN_TILE_PX:
            return [Tile(index=0, row=0, col=0, box=(0, 0, width, height), png=png)]

        pad_x = round(overlap * base_w)
        pad_y = round(overlap * base_h)
        src = im if im.mode in _PNG_SAFE_MODES else im.convert("RGB")

        tiles: list[Tile] = []
        for row in range(rows):
            top = row * base_h
            # 端数は最終行へ寄せる
            bottom = height if row == rows - 1 else top + base_h
            for col in range(cols):
                left = col * base_w
                # 端数は最終列へ寄せる
                right = width if col == cols - 1 else left + base_w
                box = (
                    max(0, left - pad_x),
                    max(0, top - pad_y),
                    min(width, right + pad_x),
                    min(height, bottom + pad_y),
                )
                buf = io.BytesIO()
                src.crop(box).save(buf, format="PNG")
                tiles.append(
                    Tile(index=len(tiles), row=row, col=col, box=box, png=buf.getvalue())
                )
        return tiles
