"""Basic LOUPE icon geometry/assets tests, no Qt GUI required."""
from pathlib import Path
import unittest
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
class TestIconQualityAssets(unittest.TestCase):
    def test_size_and_aspect(self):
        im=Image.open(ROOT/'assets/loupe.png')
        self.assertEqual(im.size,(256,256))
        self.assertEqual(im.mode,'RGBA')
    def test_windows_layers(self):
        im=Image.open(ROOT/'assets/loupe.ico')
        self.assertTrue({(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)}.issubset(im.info['sizes']))
    def test_about_quality(self):
        s=(ROOT/'loupe/gui.py').read_text(encoding='utf8')
        self.assertIn('SmoothTransformation',s)
        self.assertIn('devicePixelRatioF()',s)
if __name__=='__main__': unittest.main()
