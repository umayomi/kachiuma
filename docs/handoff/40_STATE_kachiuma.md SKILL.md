# 40_STATE_kachiuma 【更新対象】現在の状態（後継モデルはこのファイルだけ更新できる）

更新ルールは 00_READ_FIRST.md 参照。更新は「ユーザーが合意した決定」の反映のみ。

## 更新履歴（必ず1行追記。日付 / モデル / 変更点 / 根拠）

- 2026-07-07 / Fable 5 / 初版作成 / 6-7月の全セッション実測・proof 4窓528R
- 2026-07-12 / Fable 5 / §2実績表示を7/1以降に変更・tally30分毎化・§3にスイープ第1窓・§4更新・§7に着差仮説追加・スコア監査(欠陥ゼロ)記録 / 本日の実装+216R窓ログ+キャッシュ監査

## 1. 定数の現行値（リポジトリの実物と一致していること）

career_score.py:
TOP3_BASE=0.25, K=4, BETA=2.5, PIVOT_CLASS=2.6, W_CLASS=0.38, W_MARGIN=0.35,
W_BAND=0.40, W_DIR=0.20, W_GOING=0.20, W_JK=0.80, W_JK_HI=4.0, JK_KNEE=0.30,
_QUAL={1:1.0, 2:0.8, 3:0.6}
既定OFFノブ: W_EDGE=0.0（棄却済）, DECAY_HALF_D=None（棄却済）,
W_DIST_PIN=0.0 / W_COURSE=0.0 / PIN_C0=3.0（★スイープ検証中・第1窓済み）

predict.py:
TAU=1.15, LAMBDA=0.0, EV_THRESHOLD=1.0, HIDDEN_MIN_DATA=3, HIDDEN_MAX_CLASS=4

race_id: 年4+場2+回2+日2+R2。場コード: 札幌01 函館02 福島03 新潟04 東京05 中山06
中京07 京都08 阪神09 小倉10。

## 2. 実測実績の扱い（2026-07-12 変更）

- **サイトの実績カードは「7/1以降」だけを表示**する（index.html の RECORD_SINCE 定数）。
  6月以前のデータは results.json に保持したまま、表示だけ絞る（削除しない）。
  集計は races 明細から算出。明細の無い旧形式には buckets 全期間表示でフォールバック。
- **tally は土日 JST 9:00〜17:30 に30分毎**で自動実行（準リアルタイム）。日・月 JST0時に
  最終回収。旧cron(0,1指定)は月火0時に動くバグだったのを修正済み。
- 参考: 6/14〜7/5（recompute後・全期間252R）の実測は バッジ複勝率28%・複回収94%
  (182件)、◎51%・83%(252件)。7/1以降の数値は母数が育つまでブレる（仕様どおり）。

## 3. proof の確定知見

- 4窓528R（〜2026-07-07）: 指標A騎手ON ベース比+11.6〜+17.3pt、複回収82〜119%。
  観測装置: 距離のみ33.7%(336/996) ＞ 場のみ30.8%(204/662) ≒ 場×距離30.3%(114/376)、
  ベース12.7%。ジェニファー型18.3%(34/186)=+5.6pt/1.94σ → B案（距離主項+場×距離補助）。
- **W_DIST_PIN/W_COURSE スイープ第1窓（216R・6/20〜7/5、2026-07-12受領）**:
  DIST_PIN=0.2 は 22.8%/+8.7pt/80.4%（現行0.0: 22.6%/+8.5pt/79.7%）で3指標僅差勝ちだが
  的中数同数のノイズ級。0.4/0.6は悪化。COURSE=0.2/0.4 は 23.4%/+9.2pt/81.2% で
  3指標勝ち（的中+2）。**採否判断は残り3窓（5/2-10, 5/16-31, 6/6-19）待ち**。
  観測(距離>場×距離)とスイープ(場×距離のみ僅効)に食い違いあり→1窓で結論しない。
- W_JK_HI: 0.0 が5窓中3窓で両指標勝ち・1窓混在・1窓(5月後半)で4.0に両指標負け
  → 一貫性未達で4.0据え置き。実測蓄積で最終決着。
- OP・重賞ガード: 4窓合算でOP層指標A 23.8%(49/206)、層内ベース約13〜16%。率は
  上回るが複回収60.6〜116.8%と不安定 → ガード維持、母数待ち。

## 4. スコアの健全性監査（2026-07-12 実施・欠陥ゼロ）

キャッシュ64,484行を監査: surface表記は 芝/ダート/障害 で出馬表側と完全一致、
going は 稍/不 の1字系で _norm_going が吸収、finish_pos無し(取消/中止)444行(0.7%)は
career_before が既に除外、重複行ゼロ。**計測バグは存在しない**。よって現時点の
スコア改善余地は「証拠待ちの重み」だけであり、コード修正は不要と判断。

## 5. 保留タスク（優先順）

1. **W_DIST_PIN/W_COURSE スイープ残り3窓**（5/2-10, 5/16-31, 6/6-19）→ 3条件で採否。
2. スイープ不発なら交互作用項「class_proven低×適性高」（観測装置の拡張から）。
3. W_JK_HI=0.0 vs 4.0 の最終決着（実測 results.json 蓄積 or 4月proof）。
4. OP・重賞ガード再判定（母数待ち）。
5. **新仮説（未着手・実装しない）**: 着差の勝ちマージン。現行は margin を
   max(0,margin) でクランプし「どれだけ千切って勝ったか」(負の着差)を捨てている。
   ノブ化してスイープする価値があるが、1の決着後に着手（多重検定を避ける）。
6. サイト小改善（未着手）: ダイジェストの候補コピー機能。

## 6. データ構造・ワークフロー・サイト機能

- predictions/{race_id}.json: トップ = race_id/date/track/race_no/race_name/
  distance_m/surface/going/race_class/post_time/updated_at/value_note/tickets/
  hidden_picks。horses[] = umaban/name/horse_id/sex_age/jockey/trainer/
  weight_carried/horse_weight/odds_win/odds_place_low/odds_place_high/popularity/
  q_win/p_win/ev_win/edge/reasons/mark/ability_prob/ability_n_data/hidden_pick。
  finish_pos は無い（着順は結果ページから tally が取得）。
- results.json: done_race_ids / buckets{戦略}{層} / races{rid:{...picks[]}}明細 / meta。
- horsedb_cache.json: {horse_id: [{date,venue,surface,distance_m,going,race_class,
  finish_pos,margin}]}。venue「2小倉1」形式→場判定は部分一致。
- ワークフロー: pipeline(土日朝) / ability_proof(手動・env経由) /
  results(土日30分毎+日月0時) / recompute(手動・騎手ON既定)。
- index.html: 2段ナビ(場タブ→Rチップ・◆件数・**発走済みは薄表示**) / ダイジェスト /
  実績カード(**7/1以降・更新時刻表示・開催当日は5分毎自動更新**・直近明細折りたたみ・
  内訳は「30%・80件」形式) / 古い予想バナー / 重賞OPピル / 発走時刻ピル+次レース
  フォーカス / 複勝オッズ / 取消コンパクト / 凡例折りたたみ。
