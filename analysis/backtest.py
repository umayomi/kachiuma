#!/usr/bin/env python3
"""
カチウマ — バックテスト（Phase 5）

「予想どおり買っていたら、回収率は何%だったか」を過去データで検証する。

入力: data/backtest/<race_id>.json
      = レース情報 + horses:[{umaban, name, odds_win, finish_pos}]
      （finish_pos = 確定着順。1着なら単勝的中）

検証する買い方（単勝・1点100円固定）:
  - ◎単勝       : 予想の本命に賭ける
  - EV≧1単勝    : カチウマが妙味ありと判定した馬に賭ける
  - 1番人気単勝  : 市場の1番人気に賭ける（基準線）

出力: 各戦略の 賭け数 / 的中 / 的中率 / 賭け金 / 払戻 / 回収率 / 収支

時系列の注意: モデルは「レース前のオッズ」しか使わないため未来情報の混入(リーク)は無い。
（Phase4でMLを足す時は、学習に未来結果を混ぜないよう別途厳重に管理する）

使い方:
  python analysis/backtest.py --in data/backtest
  python analysis/backtest.py --demo          # 合成データで自己テスト
"""

from __future__ import annotations
import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import predict  # 同じ予想ロジックを使う  # noqa: E402

UNIT = 100  # 1点の賭け金（円）


def _finish(horse: dict) -> int | None:
    return horse.get("finish_pos")


STRATEGIES = {
    "◎単勝": lambda pred: [h for h in pred["horses"] if h.get("mark") == "◎"],
    "EV≧1単勝": lambda pred: [h for h in pred["horses"]
                             if h.get("ev_win", 0) >= predict.EV_THRESHOLD],
    "1番人気単勝(基準)": lambda pred: [h for h in pred["horses"]
                                  if h.get("popularity") == 1],
}


def run(races: list[dict]) -> dict:
    stats = {name: {"bets": 0, "hits": 0, "stake": 0, "payout": 0.0} for name in STRATEGIES}
    used = 0
    for race in races:
        # オッズが揃っていないレースはスキップ
        rated = [h for h in race.get("horses", []) if h.get("odds_win") and h["odds_win"] > 1.0]
        if len(rated) < 2 or not any(_finish(h) for h in race["horses"]):
            continue
        used += 1
        pred = predict.build_race_prediction(race)
        for name, pick in STRATEGIES.items():
            for h in pick(pred):
                s = stats[name]
                s["bets"] += 1
                s["stake"] += UNIT
                if _finish(h) == 1:
                    s["hits"] += 1
                    s["payout"] += UNIT * h["odds_win"]
    return {"races_used": used, "stats": stats}


def report(result: dict) -> str:
    lines = [f"=== バックテスト結果（対象 {result['races_used']} レース / 1点{UNIT}円）==="]
    lines.append(f"{'戦略':<16}{'賭数':>5}{'的中':>5}{'的中率':>7}{'賭金':>9}{'払戻':>10}{'回収率':>8}{'収支':>10}")
    for name, s in result["stats"].items():
        if s["bets"] == 0:
            lines.append(f"{name:<16}{'0':>5}  （該当なし）")
            continue
        hit_rate = s["hits"] / s["bets"] * 100
        roi = s["payout"] / s["stake"] * 100 if s["stake"] else 0
        pl = s["payout"] - s["stake"]
        lines.append(f"{name:<16}{s['bets']:>5}{s['hits']:>5}{hit_rate:>6.1f}%"
                     f"{s['stake']:>9,}{int(s['payout']):>10,}{roi:>7.1f}%{int(pl):>+10,}")
    lines.append("")
    lines.append("※回収率100%超でプラス。控除率(約20-30%)があるため、市場ベースの予想は")
    lines.append("  80%前後に収束しがち。それを継続的に超えられるかが“本物の優位性”の基準。")
    return "\n".join(lines)


def demo_dataset(n_races: int = 300, seed: int = 7) -> list[dict]:
    """合成データ: 市場が正しい(=控除の壁)世界。回収率が80%前後に出ることを確認。"""
    rng = random.Random(seed)
    races = []
    for r in range(n_races):
        n = rng.choice([8, 10, 12, 14, 16])
        # それっぽいオッズ列（控除込みで合計>1になるように)
        base = sorted([rng.uniform(0.02, 0.45) for _ in range(n)], reverse=True)
        over = 1.20 + rng.uniform(0, 0.10)            # overround 1.2〜1.3
        probs = [b / sum(base) for b in base]          # 真の勝率(=正規化)
        odds = [round(1.0 / (p * over), 1) for p in probs]
        # 真の勝率に従って勝ち馬を抽選
        winner = rng.choices(range(n), weights=probs, k=1)[0]
        horses = [{"umaban": i + 1, "name": f"馬{i+1}", "jockey": "J",
                   "odds_win": odds[i], "finish_pos": (1 if i == winner else 2)}
                  for i in range(n)]
        rng.shuffle(horses)
        for i, h in enumerate(horses):
            h["umaban"] = i + 1
        races.append({"race_id": f"demo{r:04d}", "date": "2026-01-01",
                      "track": "デモ", "race_no": 1, "race_name": "合成",
                      "distance_m": 1600, "surface": "芝", "going": "良", "horses": horses})
    return races


def load_dataset(indir: Path) -> list[dict]:
    races = []
    for f in sorted(indir.glob("*.json")):
        if f.name == "index.json":
            continue
        races.append(json.loads(f.read_text(encoding="utf-8")))
    return races


def main():
    ap = argparse.ArgumentParser(description="カチウマ バックテスト")
    ap.add_argument("--in", dest="indir", default="data/backtest")
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()

    if args.demo:
        races = demo_dataset()
    else:
        indir = Path(args.indir)
        races = load_dataset(indir) if indir.exists() else []
        if not races:
            print("データが無いため --demo 相当で動作します")
            races = demo_dataset()

    print(report(run(races)))


if __name__ == "__main__":
    main()
