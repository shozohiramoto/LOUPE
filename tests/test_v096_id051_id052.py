"""v0.9.6 ID051/ID052: provenance semantics and clear application naming."""
import ast
from pathlib import Path
import pytest
from loupe.orthogonal.report_provenance import orthogonal_provenance_lines

ROOT=Path(__file__).resolve().parents[1]

def _meta(plane='YZ',**kw):
    m={
        'plane':plane,'fixed_axis':'X' if plane=='YZ' else 'Y',
        'fixed_index_px':7, 'z_start_zero_based_inclusive':50,
        'z_stop_zero_based_exclusive':60, 'source_first_slice_index':150,
        'source_last_slice_index':159,'output_shape_row_col':[10,2048],
        'dtype':'float32', 'horizontal_spacing_um':0.65,
        'vertical_z_spacing_um':0.65,
        'in_plane_calibration_source':'bl09w_legacy_tiff_header',
        'z_calibration_source':'assumed_isotropic_ct',
        'generated_utc':'2026-10-19T10:42:00+00:00'}
    m.update(kw)
    return m

def test_cut_position_and_file_ordinals_are_independently_named():
    lines=orthogonal_provenance_lines(_meta())
    assert len(lines)==6
    assert 'YZ (fixed X)' in lines[0]
    assert 'X=8 px (1-based, internal 7)' in lines[0]
    assert '+Y → right' in lines[1]
    assert 'numeric Z → down' in lines[1]
    assert 'rec00150–rec00159' in lines[2]
    assert 'ordinal slices 51–60' in lines[2]
    assert '0.65 µm/px' in lines[3]
    assert 'ISOTROPIC ASSUMPTION' in lines[3]
    assert 'float32' in lines[4]
    assert 'no interpolation / resampling / 8-bit conversion' in lines[4]
    assert 'Physical Z up/down NOT verified' in lines[5]


def test_zx_native_and_custom_z_calibration():
    m=_meta('ZX',fixed_index_px=0,vertical_z_spacing_um=1.25,
            z_calibration_source='user_verified')
    lines=orthogonal_provenance_lines(m)
    assert 'ZX (fixed Y)' in lines[0]
    assert 'Y=1 px (1-based, internal 0)' in lines[0]
    assert '+X → right' in lines[1]
    assert '1.25 µm/slice [operator-verified entry]' in lines[3]


def test_uncalibrated_is_not_falsely_implied():
    lines=orthogonal_provenance_lines(_meta(horizontal_spacing_um=None,
                                           vertical_z_spacing_um=None,
                                           z_calibration_source='uncalibrated'))
    assert lines[3].count('unverified (no physical scale)')==2

@pytest.mark.parametrize('change',[{'plane':'XY'}, {'fixed_axis':'Y'},
   {'z_stop_zero_based_exclusive':50}, {'output_shape_row_col':[9,2048]}])
def test_invalid_provenance_is_rejected(change):
    with pytest.raises((ValueError,KeyError)):
        orthogonal_provenance_lines(_meta(**change))


def test_report_png_pdf_both_include_same_native_metadata():
    report=(ROOT/'loupe/report.py').read_text(encoding='utf-8')
    widget=(ROOT/'loupe/orthogonal/high_resolution_widget.py').read_text(encoding='utf-8')
    ast.parse(report);ast.parse(widget)
    assert "'orthogonal_provenance':orthogonal_provenance_lines(self._result.metadata)" in widget
    assert "_paint_orthogonal_provenance(painter,panel" in report
    assert "_paint_orthogonal_provenance(painter,item" in report
    assert 'metrics.boundingRect' in report
    assert 'provenance_h' in report
    assert "func=export_pdf_report if kind=='PDF' else export_png_report" in widget


def test_native_section_visible_UI_is_unambiguous():
    viewer=(ROOT/'loupe/orthogonal/viewer.py').read_text(encoding='utf-8')
    hr=(ROOT/'loupe/orthogonal/high_resolution_widget.py').read_text(encoding='utf-8')
    assert "self.tabs.addTab(self.hr_widget,'Native Section')" in viewer
    assert "Generate NATIVE SECTION" in viewer
    assert 'detector High-reso' in viewer
    assert 'NATIVE SECTION' in hr
    assert 'Generate NATIVE SECTION' in hr
    assert "'side':'Native Section '+plane" in hr
    assert 'self.hr_widget.move_output_controls_to(navigation)' in viewer
    assert "report_menu.addAction('PDF…')" in hr


def test_actual_extraction_json_produces_matching_report_provenance(tmp_path):
    import numpy as np
    import tifffile
    from loupe.orthogonal.high_resolution import scan_series, extract_plane
    paths=[]
    for i in range(5):
        p=tmp_path/f'rec{155+i:05}.tif'
        tifffile.imwrite(p,np.arange(12,dtype=np.uint16).reshape(3,4)+i*100)
        paths.append(p)
    series=scan_series(paths)
    outcome=extract_plane(series,plane='ZX',fixed_index=1,
                          z_start=1,z_stop=4,output_dir=tmp_path/'out',
                          z_spacing_um=None)
    lines=orthogonal_provenance_lines(outcome.metadata)
    assert 'ZX (fixed Y) | Y=2 px (1-based, internal 1)' in lines[0]
    assert 'rec00156–rec00158' in lines[2]
    assert 'ordinal slices 2–4 (1-based)' in lines[2]
    assert 'uint16' in lines[4]
    assert '4×3 px' in lines[4]
    assert 'unverified' in lines[3]
    assert outcome.metadata['interpolation']=='none'
