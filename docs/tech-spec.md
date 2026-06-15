# 技術仕様 / アーキテクチャ

## 1. 全体像（3層 + 自律ランナー）

```
┌─────────────────── GitHub（公開リポジトリ・無料）───────────────────┐
│                                                                      │
│  [データ層] scraper/collect.py                                        │
│     netkeiba → 出馬表 / 結果 / 過去走 を取得 → data/raw/（非コミット） │
│                         │                                            │
│  [分析層] analysis/predict.py                                         │
│     data/raw → 推定勝率・期待値・印・根拠 → data/predictions/*.json    │
│                         │（これはコミットOK＝自作の分析出力）          │
│                         ▼                                            │
│  [自律ランナー] .github/workflows/pipeline.yml                        │
│     定期(cron)で 収集→分析→predictions.json を commit & push          │
└──────────────────────────────────┬───────────────────────────────┘
                                    │ push を検知
                          ┌─────────▼──────────┐
                          │  Vercel（無料）     │
                          │  web/ を自動デプロイ │ → スマホで閲覧
                          └────────────────────┘
```

## 2. 技術スタック（すべて無料）

| 層 | 技術 | 備考 |
|---|---|---|
| データ収集 | Python + requests + BeautifulSoup4 | 軽量。Actionsで動かす。netkeibaは概ねサーバーレンダリングHTML |
| （描画が必要な場合の保険） | Selenium + headless Chrome | requestsで取れない部分のみ。Actions分を節約するため極力使わない |
| 分析 | Python（Phase1: ルール+EV / Phase4: LightGBM） | pandas / scikit-learn / lightgbm |
| 保存形式 | JSON（予想出力）/ SQLite or parquet（蓄積・raw） | 予想JSONはフロントが直接読む |
| フロント | 素のHTML/CSS/JS（ビルド不要） | 静的配信。将来必要ならフレームワーク化 |
| ホスティング | Vercel | 公開リポジトリから自動デプロイ |
| 実行基盤 | GitHub Actions（cron） | 公開リポジトリは標準ランナー無料無制限 |

> なぜ JRA-VAN ではなく netkeiba か：JRA-VAN は高品質だが有料（月2,090円）かつ
> JV-Link が Windows 前提（Mac/スマホ非現実的）。無料・スマホ完結の制約から netkeiba 収集を採用。
> 将来 JRA-VAN に切り替えたくなったら、データ層だけ差し替えられる構造にしておく。

## 3. ディレクトリと責務

```
scraper/collect.py        # 収集の入口。--date で対象日を指定
analysis/predict.py       # 収集データ → 予想JSON
analysis/features.py      # （Phase2以降）特徴量づくり
analysis/backtest.py      # （Phase5）回収率・的中率検証
data/raw/                 # 生データ（非コミット）
data/predictions/         # 予想JSON（コミットOK）
data/sample/              # サンプル（フロントの初期表示・開発用）
web/index.html            # フロント本体
web/vercel.json           # Vercel設定
```

## 4. 予想JSONのスキーマ（フロントとの契約）

`data/predictions/<YYYYMMDD>_<track>_<R>.json`

```json
{
  "race_id": "20260621_tokyo_11",
  "date": "2026-06-21",
  "track": "東京",
  "race_no": 11,
  "race_name": "サンプルステークス",
  "distance_m": 1600,
  "surface": "芝",
  "going": "良",
  "updated_at": "2026-06-21T09:30:00+09:00",
  "horses": [
    {
      "umaban": 5,
      "name": "サンプルホース",
      "jockey": "騎手名",
      "odds_win": 4.2,
      "popularity": 2,
      "p_win": 0.31,            // 推定勝率
      "q_win": 0.238,           // 市場想定勝率(=1/odds, 控除前)
      "ev_win": 1.30,           // 期待値 = p_win × odds_win
      "edge": 0.072,            // 妙味 = p_win − q_win
      "mark": "◎",             // 印
      "reasons": [              // 根拠（わかる設計の要）
        "前走と同距離・同コースで0.2秒差の好走",
        "想定よりオッズが甘く、妙味あり(+7.2pt)"
      ]
    }
  ],
  "tickets": [                  // EVベースの買い目候補（任意）
    { "type": "単勝", "target": "5", "ev": 1.30, "stake_unit": 1 }
  ]
}
```

`data/predictions/index.json` … 直近レース一覧（フロントの入口）

## 5. GitHub Actions（自律ランナー）

- `schedule`（cron, UTC）で開催前後に起動：例) 金土日の朝に収集→分析
- `workflow_dispatch` で手動実行も可（スマホのActionsタブからボタン1つ）
- 権限：`contents: write`（predictions の commit のため）
- 生データはコミットしない（`.gitignore` で除外）

## 6. セキュリティ / マナー

- 収集は**低頻度・適切な間隔**（sleep）でアクセス。User-Agent を明示。個人利用の範囲に留める
- 認証情報・個人情報はコードに書かない（このツールは購入を扱わないので原則不要）
- robots / 利用規約に配慮。負荷をかけない

## 7. 将来の拡張ポイント（差し替え可能に）

- データ層：netkeiba → JRA-VAN へ（有料・高品質）
- 分析層：ルール → LightGBM → アンサンブル
- フロント：静的 → PWA（オフライン閲覧・ホーム追加）
