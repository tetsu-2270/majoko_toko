# 03_ARCHITECTURE.md

# アーキテクチャ設計

## 1. 目的

本システムのモジュール構成、責務、依存関係を定義する。

------------------------------------------------------------------------

# 2. アーキテクチャ方針

-   1モジュール1責務
-   疎結合
-   Workflowによる処理制御
-   DataModel経由でのみデータ受け渡し
-   外部サービスはAdapter層経由で利用

------------------------------------------------------------------------

# 3. レイヤー構成

``` text
Application
  └─ Workflow Engine

Service
  ├─ Gmail Service
  ├─ WordPress Service
  ├─ Image Service
  └─ Template Service

Domain
  ├─ MailData
  ├─ PostData
  └─ ImageData

Infrastructure
  ├─ SQLite
  ├─ Gmail API
  ├─ WordPress REST API
  └─ FileSystem
```

------------------------------------------------------------------------

# 4. Workflow

``` mermaid
flowchart TD
    A[Start]
    B[Load Config]
    C[Environment Check]
    D[Read Gmail]
    E[Parse Mail]
    F[Sort Images]
    G[Upload Images]
    H[Resolve Article Number]
    I[Build HTML]
    J[Create Post]
    K[Mark Mail]
    L[Save History]
    M[Finish]

    A-->B-->C-->D-->E-->F-->G-->H-->I-->J-->K-->L-->M
```

------------------------------------------------------------------------

# 5. モジュール責務

  モジュール           責務
  -------------------- ---------------------------
  workflow             全体制御
  config_loader        設定読込
  gmail_reader         Gmail取得
  gmail_parser         メール解析
  image_sorter         添付画像並び替え
  image_uploader       WordPress画像アップロード
  article_search       過去記事検索
  number_manager       採番
  html_builder         HTML生成
  wp_post              投稿
  gmail_marker         既読・ラベル付与
  history_repository   SQLite更新

------------------------------------------------------------------------

# 6. 依存ルール

-   workflowのみが各モジュールを呼び出す
-   モジュール同士が直接呼び出し合わない
-   共通データはDataModelを利用する

------------------------------------------------------------------------

# 7. DataModel

-   MailData
-   AttachmentData
-   PostData
-   ImageData
-   ConfigData

詳細は04_DATA_MODEL.mdで定義する。

## 7.1 添付データの受け渡し

GmailClientはMIMEメールを解析し、ファイル名を持つ各パートを`AttachmentData`
（filename / content / content_type）へ変換して`MailData.attachments`へ設定する。
GmailClientはファイル保存や画像形式判定を行わない。

```text
GmailClient
  └─ MailData.attachments: list[AttachmentData]
       └─ AttachmentManager.save() : JPG/JPEG/PNGのみをローカル保存し list[Path] を返す
            └─ ImageSorter.sort() : IMG9999→IMG0001のロールオーバーを考慮して並び替え
                 └─ WordPressClient.upload_media() : 並び替え順のままアップロード
```

添付なし・非対応形式のみの場合、`AttachmentManager.save()`後の画像が0枚となり、
Applicationはそのメールを失敗扱いとしてスキップする（投稿・履歴保存を行わない）。

## 7.2 複数メール処理の順序と実行中キャッシュ

`MailData.received_at_ms`（Gmail `internalDate`由来のepochミリ秒）を受信時刻の正本とする。
`Application.run()`は、Gmail取得直後に全メールをこの受信時刻の古い順へ安定ソートしてから
1件ずつ直列処理する（Gmail一覧の返却順は信頼しない。並列投稿は行わない）。

```text
GmailClient.fetch_unread() → list[MailData]（順不同）
  → Application._order_by_received_at() : received_at_ms昇順の安定ソート（None=不明は末尾）
    → 1件ずつ直列処理
```

1回の`Application.run()`実行中だけ、投稿成功記事を`(作品名, 話数) → (投稿タイトル, URL)`の
キャッシュ（`posted_articles`）へ保持する。話数の自動採番・前回記事解決は、WordPress検索と
このキャッシュの両方を参照する（WordPressの検索結果が直後の投稿をまだ反映しない場合が
あるため）。投稿失敗・重複履歴でスキップした記事はキャッシュへ登録しない。キャッシュは
次回起動へ永続化しない。

前回記事解決は、同一作品名の直前話（現在話数-1）のみを対象とし、次の優先順で行う。

```text
(1) 実行中キャッシュ（同一作品・直前話） → (2) WordPress標準形式 → (3) WordPress旧No形式
```

直前話が存在しない場合（第1話・欠番）は前回セクションを生成せず、それより前の話数へは
遡らない。

------------------------------------------------------------------------

# 8. エラー処理

異常発生時はWorkflowへ例外を返却する。

Workflowが以下を判断する。

-   Retry
-   Rollback
-   Logging
-   終了

------------------------------------------------------------------------

# 9. 拡張方針

以下を追加可能な構造とする。

-   Instagram
-   X
-   Threads
-   Bluesky
-   Docker
-   GUI

*End of Document*
