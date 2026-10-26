# LOUPE v0.9.8d — GitHub Desktopでの更新手順

このZIPは開発版ソースです。既存のv0.9.8作業を上書きするのではなく、必ずGitのブランチ上で更新し、差分を確認してください。`.venv_build`、`dist`、CTデータ、EXE、Windowsダンプをコミットしないでください。

1. GitHub Desktopで既存のLOUPEリポジトリを選択。
2. `develop/v0.9.8` があれば切替。v0.9.8d専用ブランチとして分ける場合は、このブランチをベースに `develop/v0.9.8d` を作成。
3. ダウンロードZIPの `LOUPE_v0.9.8d-dev` の**中身**をリポジトリにコピー。`.git`フォルダーは変更・上書きしない。
4. Changesで主な差分（`loupe/gui.py`, `bl09w_ui/qt_theme.qss`, `assets/loupe.png`, `assets/loupe.ico`, `loupe/version.py`）を確認。
5. `Commit to develop/v0.9.8d` → `Publish branch`（またはPush origin）。
6. Native SectionのP0問題とライセンス対応が未完了のため、v0.9.8dは正式リリースタグを付けず、EXEの公開も行わない。

コミット名候補：`LOUPE v0.9.8d: install approved bolder LOUPE icon`

Windowsのローカルビルドでは `build_LOUPE_v0.9.8d_exe.bat` を実行します。
ビルド後は古いアイコンのショートカットを使い回さず、新しく生成された実行ファイルを使って確認してください。Windowsのアイコンキャッシュに古い画像が残る場合があります。

**注意:** v0.9.8dはP0クラッシュの防御・ログ強化版です。Windows実機での再現テスト前にGitHub正式Releaseへ公開しないでください。
