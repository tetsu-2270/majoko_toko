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
-   PostData
-   ImageData
-   ConfigData

詳細は04_DATA_MODEL.mdで定義する。

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
