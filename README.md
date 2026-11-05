# 銅建値アプリ（スマホ版）

JX金属が公表する電気銅建値を、iPhone・Android で見られるようにする Web アプリです。
平日 8〜19時に30分ごとにJX金属のページを確認し、改定があると通知アプリ「ntfy」でお知らせします。

- `docs/` … スマホで開く画面（GitHub Pages で公開）
- `scripts/fetch.py` … 建値の取得と通知
- `.github/workflows/check.yml` … 30分ごとの自動実行

設定方法は「セットアップ手順.txt」を見てください。
