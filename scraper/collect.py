#!/usr/bin/env python3
"""
カチウマ — データ収集オーケストレーション（Phase 1）

開催日(YYYYMMDD)を受け取り:
  1) その日の race_id を全取得
  2) 各レースの出馬表(+単勝オッズ/人気)を収集 -> data/raw/<date>_shutuba.raw.json
  3) (--with-result) 結果を収集          -> data/raw/<date>_result.raw.json
  4) (--with-past)   出走馬の過去走を収集  -> data/raw/<date>_past.raw.json

生データは data/raw/（.gitignoreで除外＝コミットされない）。
出馬表の出力スキーマは analysis/predict.py がそのまま読める形に揃えてある。

使い方:
  python scraper/collect.py --date 20260621
  python scraper/collect.py --date 20260621 --with-result --with-past
  python scraper/collect.py --selftest        # ネット不要のパーサ単体テスト
"""

from __future__ import annotations
import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import netkeiba as nk  # noqa: E402

RAW_DIR = Path("data/raw")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("collect")


def _save(date: str, kind: str, payload) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out = RAW_DIR / f"{date}_{kind}.raw.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("saved -> %s", out)
    return out


def collect_day(date: str, with_result: bool, with_past: bool) -> None:
    race_ids = nk.find_race_ids(date)
    if not race_ids:
        log.warning("%s は開催が無いか、取得できませんでした", date)
        return

    # --- 出馬表 ---
    races = []
    for rid in race_ids:
        try:
            odds = nk.get_win_odds(rid)
            html = nk.get(f"{nk.BASE_RACE}/race/shutuba.html?race_id={rid}")
            race = nk.parse_shutuba(html, rid, odds_map=odds)
            race["date"] = _fmt_date(date)
            races.append(race)
        except Exception as e:  # noqa
            log.error("出馬表 失敗 %s : %s", rid, e)
    _save(date, "shutuba", races)
    log.info("出馬表: %d/%d レース取得", len(races), len(race_ids))

    # --- 結果 ---
    if with_result:
        results = []
        for rid in race_ids:
            try:
                html = nk.get(f"{nk.BASE_RACE}/race/result.html?race_id={rid}")
                results.append(nk.parse_result(html, rid))
            except Exception as e:  # noqa
                log.error("結果 失敗 %s : %s", rid, e)
        _save(date, "result", results)

    # --- 過去走 ---
    if with_past:
        horse_ids = {h["horse_id"] for r in races for h in r["horses"] if h.get("horse_id")}
        past = {}
        for hid in sorted(horse_ids):
            try:
                html = nk.get(f"{nk.BASE_DB}/horse/{hid}/")
                past[hid] = nk.parse_horse_pastruns(html, hid, n=5)
            except Exception as e:  # noqa
                log.error("過去走 失敗 %s : %s", hid, e)
        _save(date, "past", past)
        log.info("過去走: %d頭分", len(past))


def _fmt_date(d: str) -> str:
    return f"{d[0:4]}-{d[4:6]}-{d[6:8]}"


# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="カチウマ データ収集")
    ap.add_argument("--date", help="対象日 (YYYYMMDD)")
    ap.add_argument("--with-result", action="store_true", help="結果も収集")
    ap.add_argument("--with-past", action="store_true", help="過去走も収集")
    ap.add_argument("--selftest", action="store_true", help="パーサ単体テスト(ネット不要)")
    args = ap.parse_args()

    if args.selftest:
        from test_parse import run as run_tests
        run_tests()
        return

    if not args.date:
        ap.error("--date が必要です (YYYYMMDD)")
    try:
        datetime.strptime(args.date, "%Y%m%d")
    except ValueError:
        ap.error("--date は YYYYMMDD 形式")

    log.info("=== 収集開始: %s ===", args.date)
    collect_day(args.date, args.with_result, args.with_past)
    log.info("=== 収集完了 ===")


if __name__ == "__main__":
    main()
