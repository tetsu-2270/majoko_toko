# 05_DATABASE.md

# 5. データ設計

## 5.1 方針

本システムはRDBMSを必須としない構成とする。
設定・ログ・投稿履歴はローカルファイルで管理し、将来的にSQLite等へ移行可能な構成とする。

## 5.2 ディレクトリ構成

``` text
project/
├── config/
│   ├── config.yaml
│   ├── template.html
│   ├── credentials.json
│   └── token.json
├── logs/
│   └── application.log
├── history/
│   └── post_history.json
├── temp/
└── images/
```

## 5.3 設定ファイル

config.yaml 例

``` yaml
gmail:
  target_address: majokkotoko@gmail.com
  credentials_path: config/credentials.json
  token_path: config/token.json

wordpress:
  url: https://example.com
```

保持項目 - Gmail接続情報（OAuth 2.0） - WordPress接続情報 - 投稿先カテゴリ -
ログレベル - 一時フォルダ

投稿処理済みメールの重複判定は投稿履歴（5.4）の mail_message_id で行う（Gmail側のラベルには依存しない）。

## 5.4 投稿履歴

  項目              説明
  ----------------- -----------------
  post_id           WordPress記事ID
  title             記事タイトル
  category          カテゴリ
  created_at        投稿日
  mail_message_id   処理元メールID

## 5.5 ログ

出力内容 - 開始・終了時刻 - 投稿ID - アップロード画像数 - エラー内容 -
リトライ回数

## 5.6 将来拡張

-   SQLite対応
-   PostgreSQL対応
-   投稿統計
-   重複投稿検知
-   キュー管理
