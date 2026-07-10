---
name: kachiuma-dev
description: 競馬複勝予想サイト「カチウマ」(umayomi/kachiuma) の開発・検証・運用を引き継ぐスキル。カチウマ、kachiuma、複勝予想、隠れ複勝候補、career_score、ability_proof、tally、recompute、netkeiba に関する作業で必ず読む。コード変更・重み変更・proof結果解釈・サイトUI変更のいずれでも、着手前にこのスキル一式を読了すること。
---

# 【凍結・編集禁止】カチウマ開発スキル 入口

このファイルを含む handoff 一式は3区分で管理される。**区分は 00_READ_FIRST.md が定義
し、後継モデルはその更新権限ルールに従う。このファイル自体は凍結（編集禁止）。**

## 手順（毎セッション）

1. `00_READ_FIRST.md` を読む（ファイル区分・更新権限・起動チェックリスト）。
2. `30_PITFALLS.md` の該当分野を読む（yml / データ処理 / スタブ検証 / 設計ガード）。
3. `40_STATE_kachiuma.md` で現在の定数・実績・保留タスクを把握する。
4. 判断に迷ったら `10_CORE_kachiuma.md`（思想・確定判断）と
   `20_METHODOLOGY_common.md`（作業規律）に立ち返る。
5. リポジトリの実状態を tarball で取得してから編集する:
   ```bash
   curl -sL -o r.tar.gz https://codeload.github.com/umayomi/kachiuma/tar.gz/refs/heads/main
   mkdir -p repo && tar xzf r.tar.gz -C repo --strip-components=1
   ```

## 絶対規則（要約・詳細は各文書）

- 渡すファイルは**全文貼り替え**形式。diff・パッチ不可。貼り替え順を明記。
- 新しい重み・特徴量は**既定OFFノブ + 現行完全一致の数値証明**つきで入れる。
- 重みの採用は proof スイープの3条件（10_CORE 参照）を満たすまでしない。
- 検証できなかったことは「検証できなかった」と明記する。
- 更新して良いのは 40_STATE のみ。30_PITFALLS は追記のみ。他は編集禁止。
