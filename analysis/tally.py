#!/usr/bin/env python3
"""
カチウマ — 実績集計(tally): 過去の予想(data/predictions/*.json)と確定結果を突き合わせ、
印(◎○▲△)・隠れ複勝候補バッジの複勝的中率と複勝回収率を累積して data/results.json に保存。

思想:
  proof は proxy/キャッシュでの事前検証。これは「本番で実際に出した予想」の事後実測。
  よって最も信頼できる成績。特に隠れ複勝候補バッジと◎の複勝率/回収を、
  レースクラス層別つきで積み上げる（proofの層別と同じ観点で本番実測を見る）。

方式:
  各予想JSONの race_id で結果ページを1回引き、parse_result で着順、
  parse_fukusho で複勝払戻(100円あたり円)を取得。
  「予想時点の印/バッジ」は予想JSONに保存済みの mark / hidden_pick をそのまま使う
  （後知恵で付け替えない＝リークしない実測）。
  race_id をキーに冪等マージ。再実行しても二重計上しない。確定前(着順欠損)はスキップして次回拾う。

使い方:
  python analysis/tally.py                     # 全予想を対象に差分集計
  python analysis/tally.py --since 20260614     # その日以降のみ
  python analysis/tally.py --predictions data/predictions --out data/results.json
"""
from __future__ import annotations
import argparse
import glob
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta

sys.path += ["scraper", "analysis"]
import netkeiba as nk  # noqa: E402

JST = timezone(timedelta(hours=9))
UNIT = 100  # 複勝100円賭けベースで回収率を出す


def _bucket(race_class):
    if not race_class:
        return "クラス不明"
    if race_class <= 1:
        return "新馬・未勝利"
    if race_class <= 4:
        return "条件戦(1-3勝)"
    return "OP・重賞"


def _blank_stat():
    # b=対象数, t3=複勝的中数, fb=払戻取得できた対象数, fpay=複勝払戻合計(円)
    return {"b": 0, "t3": 0, "fb": 0, "fpay": 0.0}


def _accumulate(stat, hit, fuku, umaban):
    stat["b"] += 1
    if hit:
        stat["t3"] += 1
    if fuku is not None:
        stat["fb"] += 1
        if hit:
            stat["fpay"] += fuku.get(umaban, 0)


def load_results(path: str) -> dict:
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            pass
    return {"done_race_ids": [], "buckets": {}, "meta": {}}


def _ensure_bucket(agg: dict, key: str):
    """集計器 agg[strategy][bucket] を用意（欠損時）。JSON往復後の dict にも対応。"""
    marks = ["◎(本命)", "○(対抗)", "▲(単穴)", "△(連下)", "印全体(◎○▲△)", "隠れ複勝候補"]
    buckets = ["新馬・未勝利", "条件戦(1-3勝)", "OP・重賞", "クラス不明", "全体"]
    for m in marks:
        agg.setdefault(m, {})
        for b in buckets:
            cur = agg[m].get(b)
            if cur is None:
                agg[m][b] = _blank_stat()
            else:  # 既存値を数値で継続
                for k in ("b", "t3", "fb"):
                    cur[k] = int(cur.get(k, 0))
                cur["fpay"] = float(cur.get("fpay", 0.0))


MARK_TO_KEY = {"◎": "◎(本命)", "○": "○(対抗)", "▲": "▲(単穴)", "△": "△(連下)"}


def tally(pred_dir: str, out_path: str, since: str | None, sleep: float) -> None:
    store = load_results(out_path)
    done = set(store.get("done_race_ids", []))
    agg = store.get("buckets", {})
    _ensure_bucket(agg, "_root")  # ダミーで構造確認
    agg.pop("_root", None)
    for strat in ["◎(本命)", "○(対抗)", "▲(単穴)", "△(連下)", "印全体(◎○▲△)", "隠れ複勝候補"]:
        agg.setdefault(strat, {})
    # bucket 実体化
    tmp = defaultdict(lambda: defaultdict(_blank_stat))
    for strat, bmap in agg.items():
        for b, s in bmap.items():
            tmp[strat][b] = {"b": int(s.get("b", 0)), "t3": int(s.get("t3", 0)),
                             "fb": int(s.get("fb", 0)), "fpay": float(s.get("fpay", 0.0))}

    files = sorted(glob.glob(f"{pred_dir}/*.json"))
    files = [f for f in files if not f.endswith("index.json")]
    n_new, n_pending, n_skip = 0, 0, 0

    for f in files:
        try:
            pred = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        rid = pred.get("race_id")
        if not rid or not isinstance(pred.get("horses"), list):
            continue
        if rid in done:
            continue
        if since and str(pred.get("date", "")).replace("-", "") < since:
            continue

        # 結果ページ取得（確定前は着順が入らない→pendingで次回に回す）
        try:
            html = nk.get(f"{nk.BASE_RACE}/race/result.html?race_id={rid}")
            res = nk.parse_result(html, rid)
            fuku = nk.parse_fukusho(html)
        except Exception as e:
            print("skip(取得失敗)", rid, str(e).splitlines()[0][:50])
            n_skip += 1
            continue
        fin = {h["umaban"]: h.get("finish_pos") for h in res.get("horses", [])}
        if not fin or all(v is None for v in fin.values()):
            n_pending += 1
            continue  # まだ確定していない
        fuku = fuku if fuku else None

        bk = _bucket(pred.get("race_class"))

        def record(strat, umaban):
            fp = fin.get(umaban)
            if fp is None:      # 取消等で結果に無い→対象外(分母に入れない)
                return
            hit = fp <= 3
            _accumulate(tmp[strat][bk], hit, fuku, umaban)
            _accumulate(tmp[strat]["全体"], hit, fuku, umaban)

        for h in pred["horses"]:
            u = h.get("umaban")
            mk = h.get("mark")
            if mk in MARK_TO_KEY:
                record(MARK_TO_KEY[mk], u)
                record("印全体(◎○▲△)", u)
            if h.get("hidden_pick"):
                record("隠れ複勝候補", u)

        done.add(rid)
        n_new += 1
        if sleep:
            time.sleep(sleep)

    # 保存（数値のみのdictへ）
    out_buckets = {strat: {b: s for b, s in bmap.items()} for strat, bmap in tmp.items()}
    store = {
        "updated_at": datetime.now(JST).isoformat(timespec="seconds"),
        "done_race_ids": sorted(done),
        "n_races": len(done),
        "buckets": out_buckets,
        "meta": {"unit": UNIT, "note": "本番予想の事後実測。複勝率=3着内率、複勝回収率=払戻取得レースのみ100円賭け。"},
    }
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    json.dump(store, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # ログ（人が読む要約）
    def line(strat, b="全体"):
        s = tmp[strat][b]
        if not s["b"]:
            return f"  {strat:<16}{b:<12}: データなし"
        t3 = s["t3"] / s["b"] * 100
        rec = (s["fpay"] / s["fb"]) if s["fb"] else None
        rp = f"複回収 {rec:5.1f}%" if rec is not None else "複回収  -  "
        return f"  {strat:<16}{b:<12}: {s['b']:>4}件 複勝率 {t3:5.1f}% ({s['t3']}/{s['b']})  {rp}"

    print(f"新規集計 {n_new}R / 確定待ち {n_pending}R / 取得失敗 {n_skip}R / 累積 {len(done)}R")
    print("―― 実測成績（全体）――")
    for strat in ["隠れ複勝候補", "◎(本命)", "印全体(◎○▲△)"]:
        print(line(strat))
    print("―― 隠れ複勝候補：レースクラス層別 ――")
    for b in ["新馬・未勝利", "条件戦(1-3勝)", "OP・重賞"]:
        print(line("隠れ複勝候補", b))


def main():
    ap = argparse.ArgumentParser(description="カチウマ 実績集計(tally)")
    ap.add_argument("--predictions", default="data/predictions")
    ap.add_argument("--out", default="data/results.json")
    ap.add_argument("--since", default=None, help="YYYYMMDD 以降のみ集計")
    ap.add_argument("--sleep", type=float, default=0.5)
    args = ap.parse_args()
    tally(args.predictions, args.out, args.since, args.sleep)


if __name__ == "__main__":
    main()
