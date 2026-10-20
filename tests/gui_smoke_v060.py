"""Run on Windows with v0.6.0 dependencies: python tests/gui_smoke_v060.py"""
import sys
from pathlib import Path
import numpy as np
from PySide6 import QtWidgets, QtCore
from loupe.gui import MainWindow, ContrastDialog
from loupe.report import render_report_image
from loupe.version import APP_VERSION
from loupe.app_icon import icon_path

app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
w=MainWindow()
assert not w.windowIcon().isNull()
assert w.profile_source.count()==1
assert w.panels[0].cal_size.decimals()==2
p=w.panels[0]
p.current=np.arange(256*256,dtype=np.float32).reshape(256,256)
p._auto_levels=(256.,65535.)
p.set_manual_levels(256.,65535.)
d=ContrastDialog(p,w)
d._set(100.,1000.)
assert not p.auto.isChecked() and p.lo.value()==100
assert p.hi.value()==1000
d.close()
p.set_profile_active(True)
assert p.image_profile_splitter.widget(1) is p.profile_plot
p.set_profile_active(False)
assert not p.profile_plot.isVisible()
payload={'image':p.current,'levels':(100,1000),'view_range':((0,256),(0,256)),
         'path':'test.tif','side':'VIEW 1','slice':1,'calibration':{'enabled':False},
         'annotations':[],'profile':None}
img=render_report_image([payload]);assert not img.isNull()
assert APP_VERSION.startswith('0.7.0-beta.')
print(f'LOUPE v{APP_VERSION} Qt smoke PASS')
w.close()
