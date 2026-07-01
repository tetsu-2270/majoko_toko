# 18. リリース手順

## リリース前

-   テスト完了
-   レビュー完了
-   バックアップ取得
-   config.yaml確認

## リリース

``` bash
git pull
pip install -r requirements.txt
python main.py
```

## リリース後確認

-   Gmail接続
-   WordPress接続
-   下書き投稿
-   ログ確認

## ロールバック

1.  バックアップ復元
2.  旧バージョンへ戻す
3.  動作確認

## バージョン管理

-   MAJOR: 大規模変更
-   MINOR: 機能追加
-   PATCH: バグ修正
