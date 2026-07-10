# 40_STATE_kachiuma 【更新対象】現在の状態（後継モデルはこのファイルだけ更新できる）

更新ルールは 00_READ_FIRST.md 参照。更新は「ユーザーが合意した決定」の反映のみ。

## 更新履歴（必ず1行追記。日付 / モデル / 変更点 / 根拠）

- 2026-07-07 / Fable 5 / 初版作成 / 6-7月の全セッション実測・proof 4窓528R

## 1. 定数の現行値（リポジトリの実物と一致していること）

career_score.py:
TOP3_BASE=0.25, K=4, BETA=2.5, PIVOT_CLASS=2.6, W_CLASS=0.38, W_MARGIN=0.35,
W_BAND=0.40, W_DIR=0.20, W_GOING=0.20, W_JK=0.80, W_JK_HI=4.0, JK_KNEE=0.30,
_QUAL={1:1.0, 2:0.8, 3:0.6}
既定OFFノブ: W_EDGE=0.0（棄却済）, DECAY_HALF_D=None（棄却済）,
W_DIST_PIN=0.0 / W_COURSE=0.0 / PIN_C0=3.0（★スイープ検証中）

predict.py:
TAU=1.15, LAMBDA=0.0, EV_THRESHOLD=1.0, HIDDEN_MIN_DATA=3, HIDDEN_MAX_CLASS=4

race_id: 年4+場2+回2+日2+R2。場コード: 札幌01 函館02 福島03 新潟04 東京05 中山06
中京07 京都08 阪神09 小倉10。

## 2. 実測実績（recompute 後・騎手ON・現行ロジック / 252R 時点）

- 隠れ複勝候補: 複勝率 28% ・複回収 94%（182件。新馬未勝利 30%/110件、条件戦 25%/72件）
- ◎本命: 複勝率 51%・複回収 83%（252件）
- 参考ベース: 人気4+ベタ買い 複勝率 12〜13%・複回収 68〜75%
- 表現上の注意: 複回収は 100% 未満・母数小。「ベタ買いより明確に良いが確定はこれから」。

## 3. proof の確定知見（4窓528R / 2026-07-07 集計）

- 指標A（実力top3×人気4+）騎手ON: ベース比 +11.6〜+17.3pt、複回収 82〜119%。
  5月に広げても維持。
- 観測装置（適性率>=0.5 & n>=3 の実3着内率、ベースライン人気4+ 12.7%）:
  距離のみ 33.7% (336/996) ＞ 場のみ 30.8% (204/662) ≒ 場×距離 30.3% (114/376)。
  ジェニファー型（実力top3外×人気4+×場×距離適性）18.3% (34/186) = +5.6pt / 1.94σ。
- 距離が主役 → B案採用（距離ピンポイント主項 + 場×距離補助項。「場のみ」不採用）。
- W_JK_HI: 0.0 が 3/4 窓で僅差首位だがノイズ範囲 → 4.0 据え置き。実測蓄積で最終決着。
- OP・重賞ガード再判定の材料: 4窓合算で OP 層の指標A 23.8% (49/206)、層内ベース約
  13〜16%。率は上回るが複回収 60.6〜116.8% と不安定 → ガード維持、母数待ち。

## 4. 保留タスク（優先順）

1. **W_DIST_PIN / W_COURSE スイープの結果待ち**（実装・配布済み。候補
   PIN=[0,0.2,0.4,0.6], COURSE=[0,0.2,0.4]）。採用は 10_CORE §3 の3条件。
   既知事実: この項は**ジェニファー個体を最下位から救済しない**（同レースの
   距離pin率 0.5 は他馬と横並び。prob 2.4%→2.8% だが順位不変）。効くとすれば
   距離巧者コホート全体の底上げ。個体救済を採用基準にしないこと。
2. スイープ不発なら次仮説は交互作用項「class_proven 低 × 適性高」
   （ジェニファーの真の特異点）。観測装置の拡張から入る。
3. W_JK_HI=0.0 vs 4.0 の最終決着（実測 results.json の蓄積 or 4月 proof）。
4. OP・重賞ガード再判定（§3 の材料の母数が増えたら）。
5. サイト小改善（未着手）: ダイジェストの候補コピー機能。

## 5. データ構造（コード変更に追随して更新する）

- predictions/{race_id}.json: トップ = race_id/date/track/race_no/race_name/
  distance_m/surface/going/race_class/post_time/updated_at/value_note/tickets/
  hidden_picks。horses[] = umaban/name/horse_id/sex_age/jockey/trainer/
  weight_carried/horse_weight/odds_win/odds_place_low/odds_place_high/popularity/
  q_win/p_win/ev_win/edge/reasons/mark/ability_prob/ability_n_data/hidden_pick。
  **finish_pos は無い**（事前予想）。着順は結果ページから（tally）。
- results.json: done_race_ids（冪等キー）/ buckets{戦略}{層}{b,t3,fb,fpay} /
  races{rid:{date,track,race_no,race_name,race_class,picks[]}}（個別着順明細・
  バックフィル対応）/ meta。
- horsedb_cache.json: {horse_id: [{date,venue,surface,distance_m,going,race_class,
  finish_pos,margin}]}。venue は「2小倉1」形式 → 場判定は部分一致。
  場×距離ピンポイント集計はこのキャッシュだけで可能（追加取得不要）。
- netkeiba API: 単勝 type=1 / 複勝 type=2（{馬番:[下限,上限,...]}・並びは実サイトで
  確認済み）。発走時刻は RaceData01「HH:MM発走」から。

## 6. ワークフローとサイト機能の現状

- pipeline.yml（本番・土日朝 JST）/ ability_proof.yml（手動・TEST_START/TEST_END は
  env 経由）/ results.yml（tally・日月 JST0時）/ recompute.yml（手動・騎手ON既定・
  reset_results オプション）。
- index.html: 2段ナビ（場タブ→Rチップ・◆件数）/ 隠れ複勝候補ダイジェスト
  （1レース1チップ）/ 実績カード（数字常時+直近結果明細は折りたたみ）/
  古い予想バナー / 重賞OPピル / 発走時刻ピル+次レース自動フォーカス（JST）/
  複勝オッズ表示 / 取消馬コンパクト / 凡例折りたたみ
  （localStorage: kachiuma_legend, kachiuma_seen）。
