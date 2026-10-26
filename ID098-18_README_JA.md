# LOUPE ID098-18：Native Section異常終了の暫定診断版

**元版:** v0.9.7 (2026-10-23に提供されたソース)  
**目的:** Windows例外 `0xC0000374` の原因切り分け。クラッシュ修正済みを保証する版ではありません。  
**変更箇所:** `loupe/orthogonal/high_resolution.py`, `loupe/orthogonal/high_resolution_widget.py`, `loupe/diagnostics.py`。

## 確認されたコード上の問題と処置
1. `tifffile.memmap(path)` はデフォルトで `mode='r+'` (読み書き可)。元CT画像を読み取り専用にするため `mode='r'` に修正。
2. `np.memmap._mmap.close()` を配列オブジェクトが残っている間に明示実行する書き方は危険。NumPy側の寿命管理で解放するよう変更。
3. Native Sectionのスキャン、生成、TIFF再読込、GUI表示、ROIへの受け渡しの前後に段階ログを追加。
4. Bug Reportに**直前2セッション**のログも含めるよう修正。

上記は予防的な変更であり、これだけで実際の `0xC0000374` が解消したと判断できません。特にWindows + PySide6 のGUI動作は未検証です。

## 安全な切り分け（先にこちらを実行）
1. 元の v0.9.7 EXE / ソースフォルダーは残す。
2. このZIPを**別フォルダー**に展開する。`.venv_build` や `dist` は同梱しません。Pythonと必要ライブラリは既存の共有環境を使用します。
3. `run_native_section_probe.bat` に、CT再構成フォルダまたは `recNNNNN.tif` をドラッグ＆ドロップする。
4. 原則として先頭24スライスを `memmap` と `decode` の双方で処理します。元画像を変更しません。中間結果はWindowsの `%%TEMP%%\LOUPE_native_probe_...` に出力されます。
5. **`probe_summary.json` と `probe_progress.jsonl` のみ**内容を確認して共有してください。その他の中間ファイルには元データの位置情報などが含まれる可能性があります。
6. 2方式とも成功すれば抽出エンジンの基礎経路は動作するものの、GUIのクラッシュ原因は残り得ます。次に別フォルダーの診断版LOUPEを起動し、問題の操作を行い、Bug Reportを採取してください。安全確認ができるまで大容量の繰り返し実行は避けます。

コマンドラインでは `run_native_section_probe.bat "D:\\CT\rec00001.tif" --full` とすることで全スライスでの検証もできますが、まず24スライスで確認することを推奨します。

## 検証済み範囲
- Linux / Python 3.13 のソース単体・headlessユニットテスト（Windows GUI / EXE の実機確認ではない）。
- ソースの改変差分は `ID098-18_changes.patch` に記録。
