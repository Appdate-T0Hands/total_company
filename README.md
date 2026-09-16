# total_company

4社（腎クリ・EJ・はれのこ・Appdate）の月次 BS/PL を統一科目で集計し、ブラウザで見るダッシュボード。

## 必要環境

- Python 3.10+
- 依存: PyYAML（`requirements.txt`）

```powershell
cd devroot\total_company
pip install -r requirements.txt
```

## 起動（ダッシュボード）

プロジェクトルートで `PYTHONPATH=src` を通して実行する。

```powershell
cd devroot\total_company
$env:PYTHONPATH = "src"
python -m total_company dashboard --serve --open
```

- 表: http://127.0.0.1:8765/index.html（科目・月のヘッダー行は固定）
- グラフ: 科目クリックで別ウィンドウが開く（モニター2枚目推奨）
- グラフ種類: 棒グラフ（デフォルト）/ 折れ線、月次推移 / 同月比較
- ポート変更: `--port 9000`
- 生成だけ（サーバーなし）: `python -m total_company dashboard`
- 特定会社のみ: `--company jincli`

停止はターミナルで `Ctrl+C`。

## データの置き方

```
data/
  確定/{会社}/     … 確定済み CSV
  未確定/{会社}/   … 未確定 CSV（UI に紫バッジ）
```

同じ期間が両方にある場合は **確定を優先**。

| 会社 ID | 名称 | 形式 | 決算月 |
|---------|------|------|--------|
| jincli | 医療法人きたかみ腎クリニック | freee 月次推移 | 7月 |
| ej | 株式会社EJ | MF Cloud 月次推移 | 9月 |
| harenoko | 株式会社はれのこ | freee 月次推移 | 5月 |
| appdate | 株式会社Appdate | freee 月次推移 | 3月 |

CSV を追加・更新したら、ダッシュボードを再生成する。

```powershell
$env:PYTHONPATH = "src"
python -m total_company dashboard
```

## その他のコマンド

```powershell
# 未マッピング科目の確認
python -m total_company scan

# 会社の raw 科目名一覧
python -m total_company list-accounts jincli

# 統一科目への変換結果を表示
python -m total_company normalize jincli
```

## 設定ファイル

| ファイル | 内容 |
|----------|------|
| `config/companies.yaml` | 会社定義・会計ソフト形式 |
| `config/dashboard.yaml` | 合算グループ |
| `config/display_chart.yaml` | 表示用ロールアップ（標準科目） |
| `config/account_mapping.yaml` | raw 科目名の正規化 |

## 出力

- `output/dashboard/` … 生成された HTML/JS/CSS（`.gitignore` 対象）
  - `index.html` … メイン画面
  - `data.json` … 集計データ

## リポジトリ

https://github.com/Appdate-T0Hands/total_company
