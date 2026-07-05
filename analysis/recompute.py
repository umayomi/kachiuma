#!/usr/bin/env python3
"""
カチウマ — recompute: 過去の予想を「現行ロジック」で打ち直す。

背景:
  ロジック（cp=None修正・馬場正規化・障害分離・OP重賞ガード・LAMBDA=0 等）を短期間に
  更新したため、data/predictions/*.json には旧ロジックで出した mark / hidden_pick が
  混在している。tally はそれをそのまま集計するので、実績が旧ロジック成績に薄まる。
  → 現行ロジックで全予想を打ち直し、実績を「今のカチウマの実力」に揃える。

方式（完全オフライン・ライブ取得なし）:
  各予想JSONに保存済みの馬(umaban/horse_id/jockey/odds_win) を入力に、
  - キャリアは horsedb_cache.json から取得（予想馬は100%キャッシュ済を確認済み）
  - 今日条件(surface/distance/going/race_class/direction)は、予想JSONに有ればそれを、
    無ければ結果ページ(netkeiba.parse_result)から復元（tallyと同じ経路）
  - 騎手複勝率は umarengod をライブで引けないので、既定では騎手OFFで再計算する。
    （--with-jockey 指定かつ Actions 上なら騎手も引く。ただし過去日ぶんは時間がかかる）
  現行 enrich と同じ ability_probs を呼び、predict.assign_marks / assign_hidden_picks を
  現行コードで適用して mark/ability_prob/hidden_pick/p_win/ev 等を再生成し、JSONを上書き。

注意:
  - 騎手OFFで打ち直すと、本番(騎手ON)と厳密には一致しない。ただし proof の指標Aは
    騎手ON/OFFで数pt差であり、旧ロジック混在を除くことの方が実績への影響が大きい。
    騎手を含めた完全再現をしたい場合は Actions 上で --with-jockey を使う。
  - going 復元のため結果ページを引く（--no-fetch で抑止＝JSONにある条件のみ使用）。

使い方:
  python analysis/recompute.py --in data/predictions            # 全予想を現行ロジックで再計算
  python analysis/recompute.py --in data/predictions --since 20260614
  python analysis/recompute.py --in data/predictions --no-fetch # 結果ページを引かない(going補完なし)
"""
from __future__ import annotations
import argparse
import glob
import json
import math
import os
import sys
import time

sys.path += ["scraper", "analysis"]
import career_score as C      # noqa: E402
import predict as PRED        # noqa: E402
try:
    import netkeiba as nk
except Exception:
    nk = None

C.W_JK_HI = 4.0   # 現行設定を明示（enrich と同値）

DEFAULT_CACHE = "data/horsedb_cache.json"


def load_json(path):
    return json.load(open(path, encoding="utf-8"))


def _need_condition(pred: dict) -> bool:
    """今日条件が欠けている（=古い予想）か。going か race_class が無ければ復元したい。"""
    return pred.get("going") is None or pred.get("race_class") is None


def _restore_condition(pred: dict, sleep: float) -> dict:
    """結果ページから surface/distance/going/race_class/direction を補う。失敗時は現状維持。"""
    if nk is None:
        return pred
    rid = pred.get("race_id")
    try:
        html = nk.get(f"{nk.BASE_RACE}/race/result.html?race_id={rid}")
        head = nk.parse_result(html, rid)
    except Exception as e:
        print("  cond復元失敗", rid, str(e).splitlines()[0][:40])
        return pred
    for k in ("surface", "distance_m", "going", "race_class", "direction", "track"):
        if pred.get(k) is None and head.get(k) is not None:
            pred[k] = head[k]
    if sleep:
        time.sleep(sleep)
    return pred


def recompute_race(pred: dict, cache: dict, jk_by=None) -> dict:
    """1レースを現行ロジックで打ち直す。predのhorses(umaban/horse_id/jockey/odds_win)を使う。"""
    ds = str(pred.get("date") or "").replace("-", "")
    rated = [h for h in pred.get("horses", []) if h.get("odds_win") and h["odds_win"] > 1.0]
    if len(rated) >= 2 and ds:
        cmap = {h["umaban"]: cache.get(h.get("horse_id"), []) for h in rated}
        probs, feats = C.ability_probs(cmap, {**pred, "horses": rated}, ds, jk_by_umaban=jk_by)
        for h in rated:
            p = probs.get(h["umaban"])
            if p and p > 0:
                h["ability_prob"] = round(p, 4)
                h["form_score"] = round(math.log(p), 4)
                h["ability_n_data"] = feats[h["umaban"]]["n_data"]
            else:
                for k in ("ability_prob", "form_score", "ability_n_data"):
                    h.pop(k, None)
    # 現行 predict をそのまま適用（de-vig, p, EV, 印, 隠れ複勝候補, tickets, reasons）
    return PRED.build_race_prediction(pred)


def main():
    ap = argparse.ArgumentParser(description="カチウマ recompute: 過去予想を現行ロジックで再計算")
    ap.add_argument("--in", dest="indir", default="data/predictions")
    ap.add_argument("--cache", default=DEFAULT_CACHE)
    ap.add_argument("--since", default=None, help="YYYYMMDD 以降のみ")
    ap.add_argument("--no-fetch", action="store_true", help="結果ページを引かない(going補完なし)")
    ap.add_argument("--with-jockey", action="store_true", help="騎手複勝率も引く(Actions専用・低速)")
    ap.add_argument("--sleep", type=float, default=0.4)
    args = ap.parse_args()

    cache = load_json(args.cache) if os.path.exists(args.cache) else {}
    files = sorted(glob.glob(f"{args.indir}/*.json"))
    files = [f for f in files if not f.endswith("index.json")]

    build_jk = None
    if args.with_jockey:
        try:
            import requests
            import enrich as E
            sess = requests.Session()
            build_jk = E.make_jk_tables(sess)
            print("騎手ON で再計算（umarengod をライブ取得）")
        except Exception as e:
            print("騎手テーブル準備失敗→騎手OFFで続行:", str(e)[:60])

    n_ok, n_cond, n_skip = 0, 0, 0
    changed_marks = 0
    for f in files:
        try:
            pred = load_json(f)
        except Exception:
            continue
        if not isinstance(pred, dict) or not pred.get("horses"):
            continue
        if args.since and str(pred.get("date", "")).replace("-", "") < args.since:
            continue
        old_marks = {h.get("umaban"): h.get("mark") for h in pred["horses"]}

        if not args.no_fetch and _need_condition(pred):
            pred = _restore_condition(pred, args.sleep)
            n_cond += 1

        jk_by = build_jk(pred, str(pred.get("date") or "").replace("-", "")) if build_jk else None
        try:
            newpred = recompute_race(pred, cache, jk_by=jk_by)
        except Exception as e:
            print("skip(再計算失敗)", pred.get("race_id"), str(e).splitlines()[0][:50])
            n_skip += 1
            continue

        new_marks = {h.get("umaban"): h.get("mark") for h in newpred["horses"]}
        if new_marks != old_marks:
            changed_marks += 1
        json.dump(newpred, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        n_ok += 1

    print(f"再計算 {n_ok}R（うち条件復元 {n_cond}R / 失敗 {n_skip}R）")
    print(f"◎○▲△が旧版から変化したレース: {changed_marks}/{n_ok}R")
    print("→ この後 tally.py を --since 無しで回すと、現行ロジックの実績に更新される")
    print("  （results.json の done_race_ids をリセットしたい場合は削除してから tally 実行）")


if __name__ == "__main__":
    main()
