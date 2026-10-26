# LOUPE v0.9.8c-dev — ID098-19 / ID098-20

**Status:** Windows source/EXE deployment requires real Windows validation. This
is a defensive patch and logging build, NOT a confirmed crash fix.

## ID098-19 — Native Section mouse gestures

- Native Section: middle mouse button held + drag pans image in any ROI mode.
- Mouse wheel remains zoom. Left-button ROI editing works as before.
- The shared `AnnotationViewBox` checks for Native Section before handling
  middle-drag, so the normal 1–4 VIEW linked-offset behavior is unchanged.
- Corrected an `adjust_offset` attribute lookup that was valid only for
  normal VIEW windows, not Native Section.

## ID098-20 — Orthogonal Preview access violation investigation

Reported 2026-10-25 23:36 after opening VIEW1 Orthogonal Preview while VIEW2
Native Section had completed. Windows event: python.exe, VCRUNTIME140.dll,
`0xC0000005` (access violation). Root cause is **NOT yet proven**.

- GUI preview XY/YZ/ZX images are explicitly copied to owned C-contiguous
  arrays before passing to Qt/pyqtgraph. Non-contiguous views of a readonly
  NumPy memmap no longer reach native rendering.
- Each cache construction, memmap open, GUI render and image installation is
  logged as `[PREVIEW_STAGE]`, including errors with Python traceback.
- Every preview/XY worker is tracked. Closing the Orthogonal dialog waits
  asynchronously until all workers have exited before deleting Qt signals.
- Enabled Python `faulthandler` to write a per-session `*_fatal.log` locally,
  and included current/recent fatal logs in Help → Export Bug Report.

## Windows test checklist (required before calling this fixed)

1. On a copy of the LOUPE installation, start `run.bat`; confirm title 0.9.8c.
2. Open a ~1,460-slice CT set in VIEW2; generate ZX Native Section.
3. With VIEW2 Orthogonal still open, open VIEW1 Orthogonal Preview with a
   ~2,048-slice set. Repeat once only if the first attempt passes.
4. Check log markers for `gui.preview.render.done`, `gui.ready.done`.
5. Verify middle-drag pans Native YZ/ZX when Pan/Zoom and ROI tools selected.
   Left mouse ROI creation, wheel zoom, TIFF/JSON outputs must still work.
6. Close an Orthogonal window while Preview is loading; it should show
   'Closing: cancelling image workers safely…', then close without crashing.
7. Test EXE separately after rebuilding; icons unchanged from prior icon-fix.
8. If crashing again, attach `Help → Export Bug Report` and Windows event details.

**Data policy:** Original TIFFs are never modified. The new fatal traceback
logs may contain local source or file paths; inspect them before sharing.
