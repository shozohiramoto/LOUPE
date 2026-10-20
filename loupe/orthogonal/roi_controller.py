"""Native-pixel High Resolution ROI adapter using the *same* ImagePanel interaction.

This adapter deliberately binds ImagePanel's drawing/editing implementations,
including AnnotationViewBox, MeasurePathItem and MeasurementHandle. There is no
second pyqtgraph ROI editor to drift apart from the ordinary VIEW modes.
Coordinates are local to the exported 2D orthogonal section, not global Z.
"""
from __future__ import annotations
import copy
from ..gui import ImagePanel, AnnotationViewBox


class HighResROIController:
    # Share geometry, hit targets, edits, highlights, text and preview code.
    for _name in (
        'visible_annotations','get_annotation','select_annotation',
        'roi_selection_changed','update_roi_selector','shape_path',
        'clear_edit_handles','edit_handle_positions','refresh_edit_handles',
        'preview_geometry_edit','commit_geometry_edit','replace_annotation',
        'redraw_measurements','update_annotation_styles','update_preview',
        'annotation_drag','add_count','add_annotation','delete_selected_annotation',
        'clear_visible_annotations','apply_annotations_from_history'):
        locals()[_name] = ImagePanel.__dict__[_name]
    del _name

    def __init__(self, host):
        self.host=host
        self.parent_window=host
        self.plot=host.plot
        self.current=None
        self.current_path='high_res_local'
        self.loading=False
        self.profile_active=False
        self._compact=False
        self.annotations_by_image={'high_res_local':[]}
        self.selected_annotation_id=None
        self.measurement_graphics=[]
        self.shape_items={}
        self.caption_items={}
        self.edit_handles=[]
        self._edit_preview=None
        self.preview_item=None
        self.roi_selector=host.roi_selector
        self.roi_delete=host.roi_delete
        self.roi_details=host.roi_details
        self.count_total=host.count_total

    def active_annotation_key(self):
        return self.current_path if self.current is not None else None

    def annotation_tool(self):
        return ('pan','line','rect','ellipse','count')[self.host.profile_mode.currentIndex()]

    def is_draw_tool(self):
        return self.annotation_tool() in ('line','rect','ellipse')

    def calibration(self):
        sx,sz=self.host._scale
        return {'enabled':True,'x':float(sx),'y':float(sz),'unit':'µm'} if sx and sz else {'enabled':False}

    def update_profile(self):
        self.host._update_measurement()

    def set_image(self, arr):
        self.current=None
        self.clear_edit_handles()
        for item in self.measurement_graphics:
            try:self.plot.removeItem(item)
            except (RuntimeError,ValueError):pass
        self.measurement_graphics=[]
        self.shape_items={};self.caption_items={}
        if self.preview_item is not None:
            try:self.plot.removeItem(self.preview_item)
            except (RuntimeError,ValueError):pass
            self.preview_item=None
        self.current=arr
        self.annotations_by_image={'high_res_local':[]}
        self.selected_annotation_id=None
        self.redraw_measurements()

    def all_items(self):
        return copy.deepcopy(self.visible_annotations())
