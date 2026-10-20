"""Display policy tests that run even without PySide6 installed."""
import pytest
from loupe.layout import horizontal_cells, density_for_window


@pytest.mark.parametrize('count',[1,2,3,4])
def test_all_visible_panels_one_row(count):
    assert horizontal_cells(count)==[(0,i) for i in range(count)]


@pytest.mark.parametrize('count',[-1,0,5,7,2.5,True])
def test_panel_count_validation(count):
    with pytest.raises(ValueError): horizontal_cells(count)


@pytest.mark.parametrize('count,width,expected',[
    (1,1440,'normal'),(2,1440,'normal'),
    (2,800,'compact'),(3,1440,'compact'),(4,1920,'compact'),
    (4,1024,'compact'),(4,800,'ultra'),(3,600,'ultra')])
def test_responsive_density(count,width,expected):
    assert density_for_window(count,width)==expected


def test_zero_width_invalid():
    with pytest.raises(ValueError): density_for_window(4,0)


def test_source_uses_maximized_window():
    from pathlib import Path
    source=(Path(__file__).parents[1]/'main.py').read_text(encoding='utf-8')
    assert 'window.showMaximized()' in source
    assert 'window.show()' not in source


def test_version_labels_consistent():
    from loupe import __version__
    from loupe.diagnostics import VERSION
    from loupe.version import APP_VERSION
    assert __version__ == VERSION == APP_VERSION
