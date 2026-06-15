#!/usr/bin/env python3
"""
カチウマ — 分析（予想＋期待値）（雛形 / Phase 0〜1の橋渡し）

入力: data/raw/<date>_shutuba.raw.json （Phase1で本実装）
出力: data/predictions/<race_id>.json と index.json

この雛形は「期待値(EV)・妙味(edge)・印・根拠」の計算ロジックの“骨格”を示す。
推定勝率 p の出し方は Phase 2 で本格化する（今は人気ベースの暫定式）。

使い方:
    python analysis/predict.py --in data/raw --out data/predictions
    # 入力が無い場合はサンプルで動作確認:
    python analysis/predict.py --demo
"""

import argparse
import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

JST = timezone(timedelta(hours=9))
MARKS = ["◎", "○", "▲", "△"]  # EV順に上位へ付与


def market_prob_from_odds(odds: float) -> float:
    """オッズから市場想定勝率 q（控除前の素朴な逆数）。"""
    if not odds or odds <= 1.0:
        return 0.0
    return 1.0 / odds


def normalize_market_probs(horses: list[dict]) -> None:
    """単勝オッズ由来の q を、合計が1になるよう正規化（控除分を均す）。"""
    raw = [market_prob_from_odds(h.get("odds_win", 0)) for h in horses]
    total = sum(raw) or 1.0
    for h, r in zip(horses, raw):
        h["q_win"] = round(r / total, 4)


def estimate_p_win(horses: list[dict]) -> None:
    """推定勝率 p（暫定）。
    Phase2: ここを「指数 / 近走 / コース適性」へ、Phase4: LightGBM へ差し替える。
    暫定式: 市場想定 q を土台に、人気の偏りを少し補正しただけのプレースホルダ。
    """
    n = len(horses) or 1
    for h in horses:
        q = h.get("q_win", 1.0 / n)
        # 暫定: 市場をほぼ信じつつ、わずかにフラット方向へ寄せる（穴に妙味が出やすい簡易版）
        p = 0.85 * q + 0.15 * (1.0 / n)
        h["p_win"] = round(p, 4)


def compute_ev_and_marks(horses: list[dict]) -> None:
    """EV・edge を計算し、EV上位に印を付ける。根拠も生成。"""
    for h in horses:
        odds = h.get("odds_win", 0) or 0
        p = h.get("p_win", 0)
        q = h.get("q_win", 0)
        h["ev_win"] = round(p * odds, 3) if odds else 0.0
        h["edge"] = round(p - q, 4)
        h["reasons"] = build_reasons(h)

    # EV降順で印付け（EV>1.0 のものを優先、足りなければ妙味順）
    ranked = sorted(horses, key=lambda x: (x["ev_win"], x["edge"]), reverse=True)
    for i, h in enumerate(ranked):
        h["mark"] = MARKS[i] if i < len(MARKS) and h["ev_win"] > 0 else ""


def build_reasons(h: dict) -> list[str]:
    """根拠の自動生成（“わかる設計”の核）。Phase2で材料を増やす。"""
    reasons = []
    edge_pt = round(h.get("edge", 0) * 100, 1)
    if h.get("ev_win", 0) > 1.0:
        reasons.append(f"期待値 {h['ev_win']}（理論上プラス圏）")
    if edge_pt > 0:
        reasons.append(f"市場想定よりこちらの評価が高く、妙味あり(+{edge_pt}pt)")
    elif edge_pt < 0:
        reasons.append(f"人気先行で、評価ほどの妙味は薄い({edge_pt}pt)")
    if h.get("popularity"):
        reasons.append(f"{h['popularity']}番人気（オッズ {h.get('odds_win','?')}倍）")
    return reasons or ["判断材料が少ないため保留"]


def build_race_prediction(race: dict) -> dict:
    horses = race.get("horses", [])
    normalize_market_probs(horses)
    estimate_p_win(horses)
    compute_ev_and_marks(horses)

    # EVベースの買い目候補（単勝のみの簡易版。Phase2で複勝/ワイド対応）
    tickets = [
        {"type": "単勝", "target": str(h["umaban"]), "ev": h["ev_win"], "stake_unit": 1}
        for h in horses
        if h.get("ev_win", 0) > 1.0
    ]

    return {
        **{k: race.get(k) for k in
           ("race_id", "date", "track", "race_no", "race_name",
            "distance_m", "surface", "going")},
        "updated_at": datetime.now(JST).isoformat(timespec="seconds"),
        "horses": horses,
        "tickets": tickets,
    }


def demo_race() -> dict:
    """サンプルレース（入力が無くても動作確認できる）。"""
    return {
        "race_id": "20260621_tokyo_11",
        "date": "2026-06-21", "track": "東京", "race_no": 11,
        "race_name": "サンプルステークス", "distance_m": 1600,
        "surface": "芝", "going": "良",
        "horses": [
            {"umaban": 1, "name": "アルファ", "jockey": "騎手A", "odds_win": 3.1, "popularity": 1},
            {"umaban": 5, "name": "ブラボー", "jockey": "騎手B", "odds_win": 6.8, "popularity": 3},
            {"umaban": 8, "name": "チャーリー", "jockey": "騎手C", "odds_win": 4.5, "popularity": 2},
            {"umaban": 11, "name": "デルタ", "jockey": "騎手D", "odds_win": 21.0, "popularity": 6},
            {"umaban": 14, "name": "エコー", "jockey": "騎手E", "odds_win": 12.0, "popularity": 4},
        ],
    }


def main():
    ap = argparse.ArgumentParser(description="カチウマ 分析")
    ap.add_argument("--in", dest="indir", default="data/raw")
    ap.add_argument("--out", dest="outdir", default="data/predictions")
    ap.add_argument("--demo", action="store_true", help="サンプルで動作確認")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    races: list[dict] = []
    if args.demo:
        races = [demo_race()]
    else:
        indir = Path(args.indir)
        files = sorted(indir.glob("*_shutuba.raw.json")) if indir.exists() else []
        if not files:
            print("入力が見つからないため --demo 相当で動作します")
            races = [demo_race()]
        else:
            for f in files:
                races.extend(json.loads(f.read_text(encoding="utf-8")))

    index = []
    for race in races:
        pred = build_race_prediction(race)
        out = outdir / f"{pred['race_id']}.json"
        out.write_text(json.dumps(pred, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  wrote {out}")
        top = max(pred["horses"], key=lambda x: x.get("ev_win", 0), default=None)
        index.append({
            "race_id": pred["race_id"], "date": pred["date"], "track": pred["track"],
            "race_no": pred["race_no"], "race_name": pred["race_name"],
            "best_mark_umaban": top["umaban"] if top else None,
            "best_ev": top["ev_win"] if top else None,
        })

    (outdir / "index.json").write_text(
        json.dumps({"updated_at": datetime.now(JST).isoformat(timespec="seconds"),
                    "races": index}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  wrote {outdir/'index.json'} ({len(index)} races)")


if __name__ == "__main__":
    main()
