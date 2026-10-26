"""v0.9.8d visual asset and packaging acceptance (headless)."""
from pathlib import Path
from PIL import Image
from loupe.version import APP_VERSION
from loupe.app_icon import icon_path, windows_icon_path

ROOT=Path(__file__).resolve().parents[1]


def test_approved_icon_master_is_square_and_alpha():
    assert APP_VERSION == '0.9.8d'
    with Image.open(icon_path()) as im:
        assert im.size == (256, 256)
        assert im.mode == 'RGBA'
        assert im.getpixel((0,0))[3] == 0
        assert im.getpixel((128,128))[3] == 255


def test_windows_icon_has_required_sizes():
    with Image.open(windows_icon_path()) as im:
        assert {(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)}.issubset(im.info['sizes'])


def test_original_source_artwork_is_preserved():
    assert (ROOT/'docs/LOUPE_APPROVED_ICON_ORIGINAL_20261025.png').exists()


def test_named_bat_uses_new_icon():
    build=(ROOT/'build_LOUPE_v0.9.8d_exe.bat').read_text(encoding='utf8')
    assert 'assets\\loupe.ico' in build
    assert 'assets\\loupe.png' in build
