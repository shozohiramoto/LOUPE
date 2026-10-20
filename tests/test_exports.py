import numpy as np
from loupe.exports import write_csv, write_session, read_session, imagej_macro

def test_csv(tmp_path):
    f=tmp_path/'x.csv'
    write_csv(f,[{'side':'LEFT','path':'C:/data/a.tif','slice':3,'width':7,
                  'line':((1,2),(3,2)),'profile':(np.array([0,1,2]),np.array([5,6,7]))}])
    txt=f.read_text(encoding='utf-8-sig')
    assert 'mean_intensity' in txt and 'LEFT,C:/data/a.tif,3,7,mean,1,1,2,2,6' in txt

def test_json(tmp_path):
    state={'settings':{'width_px':7},'panels':[{'side':'LEFT','path':None},{'side':'RIGHT','path':None}]}
    f=tmp_path/'compare.json';write_session(f,state)
    assert read_session(f)['settings']['width_px']==7

def test_macro():
    s={'settings':{'width_px':17},'panels':[{'side':'LEFT','path':r'C:\data\a.tif',
       'line':((10.1,20.9),(30,40)),'levels':[-1,2]},{'side':'RIGHT','path':None}]}
    macro=imagej_macro(s)
    assert 'open("C:/data/a.tif")' in macro
    assert 'setLineWidth(17)' in macro
    assert 'makeLine(10, 21, 30, 40)' in macro
