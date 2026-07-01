# 10_CONFIGURATION.md

# 10. 設定ファイル設計

## 10.1 概要

アプリケーションの設定は `config/config.yaml` で一元管理する。
認証情報や運用パラメータをコードから分離し、環境ごとの切り替えを容易にする。

------------------------------------------------------------------------

## 10.2 サンプル

``` yaml
gmail:
  host: imap.gmail.com
  port: 993
  username: your@gmail.com
  app_password: xxxxxxxxxxxxxxxx
  processed_label: Processed

wordpress:
  url: https://example.com
  username: wp_user
  application_password: xxxxxxxxxxxxxxxx
  default_status: draft
  default_category: Blog

paths:
  template: config/template.html
  temp_dir: temp
  image_dir: images
  log_file: logs/application.log
  history_file: history/post_history.json

retry:
  max_count: 3
  initial_wait_seconds: 2
  backoff: exponential

logging:
  level: INFO
```

------------------------------------------------------------------------

## 10.3 Gmail設定

  項目              説明
  ----------------- ----------------------------
  host              IMAPサーバー
  port              接続ポート
  username          Gmailアドレス
  app_password      アプリケーションパスワード
  processed_label   処理済みラベル

------------------------------------------------------------------------

## 10.4 WordPress設定

  項目                   説明
  ---------------------- ----------------------
  url                    WordPress URL
  username               ユーザー名
  application_password   Application Password
  default_status         draft / publish
  default_category       既定カテゴリ

------------------------------------------------------------------------

## 10.5 パス設定

-   template.html
-   一時保存フォルダ
-   ログファイル
-   投稿履歴ファイル

------------------------------------------------------------------------

## 10.6 リトライ設定

-   最大試行回数
-   初期待機時間
-   指数バックオフ

------------------------------------------------------------------------

## 10.7 ログ設定

利用可能なログレベル

-   DEBUG
-   INFO
-   WARN
-   ERROR

------------------------------------------------------------------------

## 10.8 セキュリティ

-   config.yaml はGit管理対象外
-   認証情報は平文公開しない
-   必要に応じて環境変数へ移行可能

------------------------------------------------------------------------

## 10.9 将来拡張

-   複数WordPressサイト対応
-   Gmailアカウント複数対応
-   OAuth認証
-   AI設定
-   プロキシ設定
