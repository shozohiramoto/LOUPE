"""Regression tests: never hand an unlevelled float TIFF to ImageItem."""
import ast
from pathlib import Path
import numpy as np
import pytest
from loupe.io import resolve_image_levels

@pytest.mark.parametrize('dtype',[np.float32,np.float64,np.uint16])
def test_auto_levels_finite_for_image_types(dtype):
    image=np.arange(100,dtype=dtype).reshape(10,10)
    lo,hi=resolve_image_levels(image)
    assert np.isfinite(lo) and np.isfinite(hi) and hi>lo

@pytest.mark.parametrize('dtype',[np.float32,np.float64])
def test_float_tiffs_with_nan_inf(dtype):
    image=np.array([[float('nan'),float('inf')],[2.0,5.0]],dtype=dtype)
    low,high=resolve_image_levels(image)
    assert np.isfinite(low) and np.isfinite(high) and high>low

def test_invalid_or_constant_data():
    arr=np.array([[np.nan,np.inf]],dtype=np.float32)
    assert resolve_image_levels(arr)==(0.,1.)
    assert resolve_image_levels(np.zeros((8,8),dtype=np.float32)) == (0.,1.)

def test_manual_levels_take_priority():
    arr=np.array([[0.,200.]],dtype=np.float32)
    assert resolve_image_levels(arr,auto=False,manual=(10,20))==(10.,20.)

@pytest.mark.parametrize('manual',[(5,5),(10,2),(float('nan'),3),(2,float('inf')),('error','bad'),None])
def test_invalid_manual_levels_fall_back(manual):
    arr=np.array([[0.,100.]],dtype=np.float32)
    low,high=resolve_image_levels(arr,auto=False,manual=manual)
    assert 0<=low<high<=100

def test_use_cached_levels_without_rescanning():
    arr=np.ones((4,4),dtype=np.float32)
    assert resolve_image_levels(arr,auto_levels=(4.,20.))==(4.,20.)

def test_every_gui_image_assignment_has_levels():
    # Source invariant catches reintroduction of the GUI paint crash even
    # when Qt is absent from the build environment.
    source=Path(__file__).resolve().parents[1]/'loupe'/'gui.py'
    tree=ast.parse(source.read_text(encoding='utf-8'))
    calls=[]
    for node in ast.walk(tree):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='setImage':
            calls.append(node)
            assert any(k.arg=='levels' for k in node.keywords), f'missing levels near line {node.lineno}'
    assert len(calls)>=2
