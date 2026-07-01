# 14_DIRECTORY_STRUCTURE.md

# 14. プロジェクト構成

## 14.1 目的

本章では、プロジェクト全体のディレクトリ構成と各ファイルの役割を定義する。

------------------------------------------------------------------------

## 14.2 推奨ディレクトリ構成

``` text
project/
├── config/
│   ├── config.yaml
│   ├── template.html
│   ├── credentials.json
│   └── token.json
├── history/
│   └── post_history.json
├── images/
├── logs/
│   └── application.log
├── temp/
├── src/
│   ├── application.py
│   ├── config_manager.py
│   ├── gmail_client.py
│   ├── attachment_manager.py
│   ├── image_sorter.py
│   ├── html_generator.py
│   ├── wordpress_client.py
│   ├── history_manager.py
│   └── log_manager.py
├── tests/
├── requirements.txt
├── main.py
└── README.md
```

------------------------------------------------------------------------

## 14.3 ディレクトリ説明

  ディレクトリ   用途
  -------------- --------------------------------
  config         設定ファイル・HTMLテンプレート
  history        投稿履歴
  images         画像保存
  logs           ログ出力
  temp           一時ファイル
  src            アプリケーション本体
  tests          テストコード

------------------------------------------------------------------------

## 14.4 命名規則

-   Pythonファイル: snake_case
-   クラス名: PascalCase
-   関数名: snake_case
-   定数: UPPER_SNAKE_CASE

------------------------------------------------------------------------

## 14.5 管理対象

Gitで管理するもの

-   ソースコード
-   テンプレート
-   ドキュメント
-   requirements.txt

Git管理対象外

-   config.yaml
-   credentials.json
-   token.json
-   application.log
-   post_history.json
-   temp/
-   images/

------------------------------------------------------------------------

## 14.6 .gitignore例

``` text
.venv/
__pycache__/
logs/
temp/
images/
history/
config/config.yaml
config/credentials.json
config/token.json
```

------------------------------------------------------------------------

## 14.7 将来拡張

-   docs/
-   docker/
-   scripts/
-   migrations/
-   plugins/
