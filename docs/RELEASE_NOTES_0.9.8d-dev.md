# LOUPE v0.9.8d — icon update (development)

Date: 2026-10-26 (JST)

## Included

- The **approved 2026-10-25** bold-stroke magnifying-glass drawing was used **unchanged within the icon**, not regenerated. Only external white background was made transparent, with a proportional resize to 256x256 RGBA.
- Windows app icon includes 16, 24, 32, 48, 64, 128, and 256 px frames. The PNG and ICO come from the same asset.
- Source artwork: `docs/LOUPE_APPROVED_ICON_ORIGINAL_20261025.png` (original, unchanged).
- All other code and functionality inherited from v0.9.8c; no changes to the Orthogonal View, Relative Linked View, RAM meter, or HIS reader.
- App/About/log/bug-report version reads `0.9.8d`; Windows build BAT renamed accordingly.

## Windows acceptance checks (NOT yet completed)

1. Open `run.bat` and confirm `About LOUPE` shows `0.9.8d` with the selected icon.
2. Build with `build_LOUPE_v0.9.8d_exe.bat`; compare taskbar, Start menu and Explorer icons with the PHASE icon on the **same display/DPI scaling**, especially at 16/24/32 px.
3. Windows Explorer may cache an older icon. Inspect the fresh EXE/shortcut before judging the replacement.
4. Recheck v0.9.8c functionality (especially ID098-19 Native Section middle-drag and ID098-20 Orthogonal Preview crash). Prior access violations are **not conclusively resolved**.

## Release status

Development only. Windows GUI and crash remediation have not been independently validated. Do not label a public stable release before completing Windows acceptance, IP/redistribution review, and third-party license compliance.
