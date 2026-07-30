"""core.visual.tiling の単体テスト。

PIL は visual extra に明示列挙されているが、実際には base 依存の python-pptx が
Pillow を無条件に要求するため、extra 無しの `uv sync` でも必ず入る
(uv.lock: python-pptx -> pillow)。よって importorskip は付けず、PIL が無ければ
落ちるべき依存の壊れとして扱う。
"""
import io

import pytest
from PIL import Image

from core.visual.tiling import MIN_TILE_PX, split_tiles


def _png(width: int, height: int, *, mode: str = "RGB", color=(255, 0, 0)) -> bytes:
    buf = io.BytesIO()
    Image.new(mode, (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


def _quadrant_png(width: int, height: int) -> bytes:
    """左上=赤 右上=緑 左下=青 右下=白 の画像。タイル内容の照合用。"""
    im = Image.new("RGB", (width, height))
    half_w, half_h = width // 2, height // 2
    for x0, y0, x1, y1, color in (
        (0, 0, half_w, half_h, (255, 0, 0)),
        (half_w, 0, width, half_h, (0, 255, 0)),
        (0, half_h, half_w, height, (0, 0, 255)),
        (half_w, half_h, width, height, (255, 255, 255)),
    ):
        im.paste(color, (x0, y0, x1, y1))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _decode_size(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as im:
        return im.size


# --- 縮退 (分割なし) ---------------------------------------------------------


def test_1x1_returns_original_bytes_unchanged():
    png = _png(400, 600)
    tiles = split_tiles(png, rows=1, cols=1, overlap=0.1)
    assert len(tiles) == 1
    t = tiles[0]
    assert (t.index, t.row, t.col) == (0, 0, 0)
    assert t.box == (0, 0, 400, 600)
    assert t.png == png  # 再エンコードしない


def test_degenerates_when_base_tile_below_min_px():
    # 100 // 4 = 25 < MIN_TILE_PX(32) -> 分割しない
    png = _png(100, 100)
    tiles = split_tiles(png, rows=4, cols=4, overlap=0.0)
    assert len(tiles) == 1
    assert tiles[0].box == (0, 0, 100, 100)
    assert tiles[0].png == png


def test_degenerates_when_only_one_axis_below_min_px():
    # 幅 200 // 2 = 100 は OK だが、高さ 40 // 2 = 20 < 32 -> 分割しない
    png = _png(200, 40)
    tiles = split_tiles(png, rows=2, cols=2, overlap=0.0)
    assert len(tiles) == 1


def test_exactly_min_tile_px_still_splits():
    # 64 // 2 = 32 == MIN_TILE_PX -> 境界値は分割する
    png = _png(64, 64)
    tiles = split_tiles(png, rows=2, cols=2, overlap=0.0)
    assert len(tiles) == 4
    assert all(t.width == MIN_TILE_PX and t.height == MIN_TILE_PX for t in tiles)


def test_cols_greater_than_width_degenerates_without_zero_division():
    png = _png(10, 10)
    tiles = split_tiles(png, rows=20, cols=20, overlap=0.5)
    assert len(tiles) == 1


# --- グリッドと順序 ----------------------------------------------------------


def test_row_major_index_assignment():
    png = _png(300, 200)
    tiles = split_tiles(png, rows=2, cols=3, overlap=0.0)
    assert [t.index for t in tiles] == [0, 1, 2, 3, 4, 5]
    assert [(t.row, t.col) for t in tiles] == [
        (0, 0), (0, 1), (0, 2),
        (1, 0), (1, 1), (1, 2),
    ]


def test_no_overlap_boxes_partition_the_image_exactly():
    png = _png(300, 200)
    tiles = split_tiles(png, rows=2, cols=3, overlap=0.0)
    assert [t.box for t in tiles] == [
        (0, 0, 100, 100), (100, 0, 200, 100), (200, 0, 300, 100),
        (0, 100, 100, 200), (100, 100, 200, 200), (200, 100, 300, 200),
    ]
    assert sum(t.width * t.height for t in tiles) == 300 * 200


def test_single_row_and_single_column_grids():
    png = _png(300, 100)
    assert [t.box for t in split_tiles(png, rows=1, cols=3, overlap=0.0)] == [
        (0, 0, 100, 100), (100, 0, 200, 100), (200, 0, 300, 100),
    ]
    png2 = _png(100, 300)
    assert [t.box for t in split_tiles(png2, rows=3, cols=1, overlap=0.0)] == [
        (0, 0, 100, 100), (0, 100, 100, 200), (0, 200, 100, 300),
    ]


# --- 端数 --------------------------------------------------------------------


def test_remainder_pixels_go_to_last_row_and_column():
    # 101 // 3 = 33 (余り2 -> 最終列), 103 // 3 = 34 (余り1 -> 最終行)
    png = _png(101, 103)
    tiles = split_tiles(png, rows=3, cols=3, overlap=0.0)
    boxes = {(t.row, t.col): t.box for t in tiles}
    assert boxes[(0, 0)] == (0, 0, 33, 34)
    assert boxes[(0, 2)] == (66, 0, 101, 34)   # 最終列は 33+2=35 幅
    assert boxes[(2, 0)] == (0, 68, 33, 103)   # 最終行は 34+1=35 高さ
    assert boxes[(2, 2)] == (66, 68, 101, 103)
    assert sum(t.width * t.height for t in tiles) == 101 * 103


# --- overlap -----------------------------------------------------------------


def test_overlap_expands_inward_and_clips_at_image_border():
    # base = (100, 100), overlap=0.25 -> pad = 25
    png = _png(200, 200)
    tiles = split_tiles(png, rows=2, cols=2, overlap=0.25)
    boxes = {(t.row, t.col): t.box for t in tiles}
    assert boxes[(0, 0)] == (0, 0, 125, 125)      # 左端・上端はクリップ
    assert boxes[(0, 1)] == (75, 0, 200, 125)     # 右端はクリップ、左へ 25 拡張
    assert boxes[(1, 0)] == (0, 75, 125, 200)
    assert boxes[(1, 1)] == (75, 75, 200, 200)


def test_overlap_uses_per_axis_base_side_length():
    # 600x200, rows=2, cols=3 -> base=(200, 100), overlap=0.1 -> pad=(20, 10)
    png = _png(600, 200)
    tiles = split_tiles(png, rows=2, cols=3, overlap=0.1)
    boxes = {(t.row, t.col): t.box for t in tiles}
    assert boxes[(0, 1)] == (180, 0, 420, 110)   # 水平±20, 垂直±10 (上はクリップ)
    assert boxes[(1, 1)] == (180, 90, 420, 200)


def test_overlap_greater_than_one_clips_to_whole_image():
    png = _png(200, 200)
    tiles = split_tiles(png, rows=2, cols=2, overlap=5.0)
    assert len(tiles) == 4
    assert all(t.box == (0, 0, 200, 200) for t in tiles)


def test_overlap_rounds_to_nearest_pixel():
    # base = 100, overlap=0.005 -> 0.5 -> round -> 0 (バンカー丸め)
    png = _png(200, 200)
    tiles = split_tiles(png, rows=2, cols=2, overlap=0.005)
    assert tiles[0].box == (0, 0, 100, 100)
    # base = 100, overlap=0.014 -> 1.4 -> 1
    tiles2 = split_tiles(png, rows=2, cols=2, overlap=0.014)
    assert tiles2[0].box == (0, 0, 101, 101)


# --- PNG の中身 --------------------------------------------------------------


def test_tile_png_size_matches_box():
    png = _png(301, 203)
    for t in split_tiles(png, rows=3, cols=2, overlap=0.2):
        assert _decode_size(t.png) == (t.width, t.height)


def test_tile_content_matches_source_region():
    png = _quadrant_png(200, 200)
    tiles = split_tiles(png, rows=2, cols=2, overlap=0.0)
    expected = {
        (0, 0): (255, 0, 0),
        (0, 1): (0, 255, 0),
        (1, 0): (0, 0, 255),
        (1, 1): (255, 255, 255),
    }
    for t in tiles:
        with Image.open(io.BytesIO(t.png)) as im:
            rgb = im.convert("RGB")
            assert rgb.getpixel((0, 0)) == expected[(t.row, t.col)]
            assert rgb.getpixel((rgb.width - 1, rgb.height - 1)) == expected[(t.row, t.col)]


def test_tiles_reassemble_into_original_when_no_overlap():
    src_bytes = _quadrant_png(201, 199)
    tiles = split_tiles(src_bytes, rows=3, cols=3, overlap=0.0)
    canvas = Image.new("RGB", (201, 199))
    for t in tiles:
        with Image.open(io.BytesIO(t.png)) as im:
            canvas.paste(im.convert("RGB"), (t.box[0], t.box[1]))
    with Image.open(io.BytesIO(src_bytes)) as original:
        assert canvas.tobytes() == original.convert("RGB").tobytes()


def test_grayscale_png_is_preserved():
    png = _png(200, 200, mode="L", color=128)
    tiles = split_tiles(png, rows=2, cols=2, overlap=0.1)
    with Image.open(io.BytesIO(tiles[0].png)) as im:
        assert im.mode == "L"
        assert im.getpixel((0, 0)) == 128


# --- 引数検証 ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("rows", "cols", "overlap"),
    [(0, 2, 0.0), (2, 0, 0.0), (-1, 2, 0.0), (2, 2, -0.1)],
)
def test_invalid_arguments_raise_value_error(rows, cols, overlap):
    with pytest.raises(ValueError):
        split_tiles(_png(200, 200), rows=rows, cols=cols, overlap=overlap)


def test_is_pure_input_bytes_not_mutated_and_repeatable():
    png = _png(300, 200)
    snapshot = bytes(png)
    first = split_tiles(png, rows=2, cols=2, overlap=0.1)
    second = split_tiles(png, rows=2, cols=2, overlap=0.1)
    assert png == snapshot
    assert [t.png for t in first] == [t.png for t in second]
    assert [t.box for t in first] == [t.box for t in second]
