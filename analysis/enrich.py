#!/usr/bin/env python3
"""
カチウマ — enrich: career_score(A) の実力prob を form_score として各馬に付与。

collect.py と predict.py の間に挟むステップ。
  data/raw/*_shutuba.raw.json を読む
  各馬のフルキャリアを取得（horsedb_cache.json を proof と共有・未取得だけ）
  career_score.ability_probs（騎手込み W_JK=0.80）でレース内・実力prob を算出
  各馬に form_score = log(prob) と ability_prob（透明性用）を書き戻して保存

なぜ log(prob) か:
  predict.estimate_p は exp(LAMBDA*(f - mean_f)) で市場確率を傾ける。
  f = log(prob) を入れると  q × (prob / 幾何平均)^LAMBDA  の自然な融合になり、
  傾けの強さは predict 側の LAMBDA 一本のノブで決まる（バックテストで採否）。

注意:
  pastrun(系統C)が付けた form_score を上書きする（A優先）。
  ライブ取得(Selenium/umarengod)は Actions 上でのみ到達可能。失敗は握りつぶして
  「その馬は form_score なし＝オッズのまま」に degrade（予想は必ず出る）。

使い方:
  python analysis/enrich.py --in data/raw            # collect の後・predict の前
  python analysis/enrich.py --in data/raw --budget-min 70
"""
from __future__ import annotations
import argparse
import glob
import json
import math
import os
import sys
import time
from pathlib import Path

sys.path += ["scraper", "analysis"]
import horsedb as hd          # noqa: E402
import career_score as C      # noqa: E402
import jockey_db as J         # noqa: E402

try:
    import requests
except Exception:             # umarengod 不通環境でも import で落ちない
    requests = None

DEFAULT_CACHE = "data/horsedb_cache.json"


# ---- horsedb_cache 入出力（proof と同じファイルを共有） -------------------
def load_cache(path: str) -> dict:
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(cache: dict, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    json.dump(cache, open(path, "w", encoding="utf-8"), ensure_ascii=False)


# ---- 騎手テーブル（proof と同一パターン: (surface,dist[,place]) でメモ化） --
def make_jk_tables(sess):
    place_memo, all_memo = {}, {}

    def _tbl(memo, key, surface, dist, ds, place):
        if key not in memo:
            try:
                memo[key] = J.fetch(sess, surface, dist, ds, place=place)
            except Exception as e:
                print("jk-fetch-fail", place, dist, str(e).splitlines()[0][:40])
                memo[key] = {}
            time.sleep(0.8)
        return memo[key]

    def build(r, ds):
        if sess is None:
            return {}
        place, surf, dist = r.get("track"), r.get("surface"), r.get("distance_m")
        if not (surf and dist):
            return {}
        sp = J._surface_param(surf)
        ptbl = _tbl(place_memo, (sp, dist, place or "ALL"), surf, dist, ds, place or "ALL")
        atbl = _tbl(all_memo, (sp, dist), surf, dist, ds, "ALL")
        out = {}
        for h in r.get("horses", []):
            cell, _ = J.resolve(ptbl, atbl, h.get("jockey") or "")
            if cell:
                out[h["umaban"]] = {"rate": J.rate(cell), "starts": cell["starts"]}
        return out

    return build


# ---- キャリア取得（proof の section2 と同じ復帰・予算ロジック） -----------
def fetch_missing(missing: list[str], cache: dict, budget_min: int) -> None:
    if not missing:
        print("取得対象なし（全頭キャッシュ済）")
        return
    driver = hd.make_driver()
    t0, budget, since = time.time(), budget_min * 60, 0

    def restart():
        nonlocal driver, since
        try:
            driver.quit()
        except Exception:
            pass
        driver = hd.make_driver()
        since = 0

    for i, hid in enumerate(missing):
        if time.time() - t0 > budget:
            print(f"!! 時間予算到達 {i}/{len(missing)}頭で中断（続きは再実行で）")
            break
        if since >= 40:
            restart()
        done = False
        for _ in range(2):
            try:
                cache[hid] = hd.trim_career(hd.fetch_horse(driver, hid, wait=1.0))
                done = True
                break
            except Exception as e:
                msg = str(e).splitlines()[0][:50]
                if any(x in msg.lower() for x in ("crash", "session", "renderer")):
                    restart()
                else:
                    print("fail", hid, msg)
                    break
        if not done:
            cache[hid] = []
        since += 1
        if i % 25 == 0:
            print(f"  ...{i}/{len(missing)} ({int(time.time() - t0)}s)")
        time.sleep(1.5)
    try:
        driver.quit()
    except Exception:
        pass


def enrich_file(path: str, cache: dict, build_jk) -> tuple[int, int]:
    """raw ファイル(レースのlist)を読み、各馬に form_score を書き戻す。
    returns (付与した馬数, 対象レース数)。"""
    lst = json.load(open(path, encoding="utf-8"))
    if isinstance(lst, dict):       # 単体レースで保存されている場合も許容
        lst = [lst]
    n_h, n_r = 0, 0
    for r in lst:
        rated = [h for h in r.get("horses", [])
                 if h.get("odds_win") and h["odds_win"] > 1.0]
        if len(rated) < 2:
            continue
        n_r += 1
        ds = str(r.get("date") or "").replace("-", "")
        cmap = {h["umaban"]: cache.get(h.get("horse_id"), []) for h in rated}
        jk_by = build_jk(r, ds)
        probs, _ = C.ability_probs(cmap, {**r, "horses": rated}, ds, jk_by_umaban=jk_by)
        for h in rated:
            p = probs.get(h["umaban"])
            if p and p > 0:
                h["form_score"] = round(math.log(p), 4)   # predict が exp(LAMBDA*(f-mean)) で傾ける
                h["ability_prob"] = round(p, 4)            # 透明性（表示・検証用）
                n_h += 1
    json.dump(lst, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return n_h, n_r


def main():
    ap = argparse.ArgumentParser(description="カチウマ enrich: career_score を form_score に")
    ap.add_argument("--in", dest="indir", default="data/raw")
    ap.add_argument("--cache", default=DEFAULT_CACHE)
    ap.add_argument("--budget-min", type=int, default=70)
    args = ap.parse_args()

    files = sorted(glob.glob(f"{args.indir}/*_shutuba.raw.json"))
    if not files:
        print(f"入力なし: {args.indir}/*_shutuba.raw.json")
        return

    races = []
    for f in files:
        d = json.load(open(f, encoding="utf-8"))
        races.extend(d if isinstance(d, list) else [d])
    hids = sorted({h["horse_id"] for r in races for h in r.get("horses", [])
                   if h.get("horse_id")})
    print(f"raw {len(files)}ファイル / {len(races)}R / ユニーク馬 {len(hids)}頭")

    cache = load_cache(args.cache)
    missing = [h for h in hids if h not in cache]
    print(f"キャッシュ済 {len(hids) - len(missing)}頭 / 取得対象 {len(missing)}頭")
    fetch_missing(missing, cache, args.budget_min)
    save_cache(cache, args.cache)
    got = sum(1 for h in hids if cache.get(h))
    print(f"カバレッジ: {got}/{len(hids)}頭")

    sess = requests.Session() if requests is not None else None
    if sess is None:
        print("requests 不在: 騎手なしで form_score を算出")
    build_jk = make_jk_tables(sess)

    tot_h, tot_r = 0, 0
    for f in files:
        nh, nr = enrich_file(f, cache, build_jk)
        tot_h += nh
        tot_r += nr
    print(f"form_score 付与: {tot_h}頭 / {tot_r}R（pastrunのform_scoreは上書き＝A優先）")


if __name__ == "__main__":
    main()
