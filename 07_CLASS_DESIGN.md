# 07_CLASS_DESIGN.md

# 7. クラス設計

## 7.1 クラス一覧

  クラス              責務
  ------------------- --------------------
  Application         全体制御
  ConfigManager       設定ファイル読込
  GmailClient         メール取得・既読化
  AttachmentManager   添付画像管理
  ImageSorter         画像並び替え
  WordPressClient     WordPress API通信
  HtmlGenerator       HTML生成
  HistoryManager      投稿履歴管理
  LogManager          ログ出力

------------------------------------------------------------------------

## 7.2 クラス構成

``` text
Application
 ├── ConfigManager
 ├── GmailClient
 ├── AttachmentManager
 ├── ImageSorter
 ├── HtmlGenerator
 ├── WordPressClient
 ├── HistoryManager
 └── LogManager
```

------------------------------------------------------------------------

## 7.3 主な責務

### Application

-   起動
-   全体フロー制御
-   例外処理

### ConfigManager

-   config.yaml 読込
-   設定値取得

### GmailClient

-   Gmail API接続（OAuth 2.0、初回ブラウザ同意・以降トークン自動更新）
-   未読メール取得（gmail.readonlyスコープ）
-   添付取得

注記: gmail.readonlyスコープでは既読化・ラベル付与はできないため、これらはGmailClientの責務から除外する。
重複処理防止は HistoryManager（投稿履歴のmail_message_id照合）が担う。

### AttachmentManager

-   添付ファイル保存
-   一時ディレクトリ管理

### ImageSorter

-   ファイル名順ソート
-   IMG9999→IMG0001 の境界考慮

### HtmlGenerator

-   template.htmlへ差し込み
-   投稿HTML生成

### WordPressClient

-   メディアアップロード
-   カテゴリ取得・作成
-   投稿作成
-   アイキャッチ設定

### HistoryManager

-   投稿履歴保存
-   重複投稿チェック（将来）

### LogManager

-   INFO/WARN/ERROR出力
-   ローテーション対応（将来）

------------------------------------------------------------------------

## 7.4 クラス依存

``` text
Application
    ↓
ConfigManager

Application
    ↓
GmailClient
    ↓
AttachmentManager
    ↓
ImageSorter
    ↓
HtmlGenerator
    ↓
WordPressClient
    ↓
HistoryManager
```

------------------------------------------------------------------------

## 7.5 設計方針

-   1クラス1責務
-   APIアクセスを集約
-   テスト容易性を重視
-   将来的なgmail.modifyスコープ対応（既読化・ラベル付与）を考慮
-   WordPress以外への拡張を容易にする

------------------------------------------------------------------------

## 7.6 将来拡張

-   AIタイトル生成クラス
-   タグ自動生成クラス
-   SQLiteRepository
-   Scheduler
-   CLIオプション管理
