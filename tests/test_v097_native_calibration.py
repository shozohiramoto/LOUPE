"""ID054 follow-up: explicit manual XY calibration for native orthogonal extraction."""
from pathlib import Path
import ast
import numpy as np
import tifffile
from loupe.orthogonal.high_resolution import scan_series,extract_plane

def test_native_xy_override_beats_header(tmp_path):
    paths=[]
    for z in range(3):
        path=tmp_path/f'rec{z:05d}.tif'
        tifffile.imwrite(path,np.full((5,6),z,dtype=np.uint16))
        paths.append(path)
    series=scan_series(paths,pixel_size_um=0.75)
    result=extract_plane(series,plane='YZ',fixed_index=2,output_dir=tmp_path/'out')
    assert result.metadata['horizontal_spacing_um']==0.75
    assert result.metadata['vertical_z_spacing_um']==0.75
    assert result.metadata['in_plane_calibration_source']=='user_verified'

def test_gui_passes_verified_pixel_size_to_native_extractor():
    root=Path(__file__).resolve().parents[1]
    hr=(root/'loupe/orthogonal/high_resolution_widget.py').read_text()
    gui=(root/'loupe/gui.py').read_text()
    ast.parse(hr);ast.parse(gui)
    assert 'self.custom_xy=QtWidgets.QCheckBox' in hr
    assert 'pixel_size_um=xy_um' in hr
    assert "if verified and not cal['enabled']" in gui
