#!/usr/bin/env python3
"""
カチウマ — 分析エンジン（Phase 2: 市場ベース＋人気-穴バイアス補正）

考え方:
  1) de-vig: 単勝オッズから控除率を除いた「市場確率 q」を算出（合計=1に正規化）
  2) 推定勝率 p: 市場確率を土台に、人気-穴バイアスを補正（q^TAU を正規化, TAU>1で本命寄り）
     → 公開オッズは過小評価されがちな本命をやや高く、過大評価されがちな穴を低く見積もる
  3) EV = p × odるds, edge = p − q
  4) 印(◎○▲△)= 実力+騎手スコア(ability_prob)の上位（方針b・proofで検証した生スコア順）
     ability_prob が無い場合のみ市場ベース p の上位にフォールバック
  5) 買い目(tickets)= EV ≧ しきい値 の「妙味」だけ（無ければ"見送り"）

正直な注意:
  公開オッズだけが入力の場合、控除率(約20%)の壁でEV>1はめったに出ない。
  「妙味なし＝見送り」が多いのは正しい。本物の優位性は特徴量を足すPhase4で。

使い方:
  python analysis/predict.py --in data/raw --out data/predictions
  python analysis/predict.py --demo
"""

from __future__ import annotations
import argparse
import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

JST = timezone(timedelta(hours=9))

# --- チューニング可能パラメータ -------------------------------------------
TAU = 1.15           # 人気-穴バイアス補正の指数（>1で本命寄り。1.0で市場そのまま）
LAMBDA = 0.6         # 実力評価(form_score)をどれだけ効かせるか（0=オッズのみ=Phase2）
EV_THRESHOLD = 1.0   # これ以上を「妙味（理論上プラス）」とみなす
HIDDEN_MIN_DATA = 3  # 隠れ複勝候補のevaluable条件（proofのMIN_DATAと同値。キャリア3走未満は対象外）
# 印の定義（予想の強さ順）
MARKS = [("◎", "本命"), ("○", "対抗"), ("▲", "単穴"), ("△", "連下")]


def market_devig(rated: list[dict]) -> float:
    """単勝オッズ → 市場確率 q（合計1に正規化）。overround(控除込み合計)を返す。"""
    raw = [1.0 / h["odds_win"] for h in rated]
    overround = sum(raw) or 1.0
    for h, r in zip(rated, raw):
        h["q_win"] = round(r / overround, 4)
    return overround


def estimate_p(rated: list[dict], tau: float = TAU) -> None:
    """推定勝率 p：市場確率 q を土台に
       (1) 人気-穴バイアス補正（q^tau）
       (2) 実力評価 form_score による相対的な傾け（market+実力の融合）
       form_score が無ければ (1) だけ＝Phase2と同じ挙動。"""
    base = [h["q_win"] ** tau for h in rated]

    fs = [h.get("form_score") for h in rated]
    have = [x for x in fs if x is not None]
    if have:
        mean_fs = sum(have) / len(have)
        tilted = []
        for b, h in zip(base, rated):
            f = h.get("form_score")
            t = math.exp(LAMBDA * (f - mean_fs)) if f is not None else 1.0
            h["_form_tilt"] = round(t, 3)
            tilted.append(b * t)
        base = tilted

    s = sum(base) or 1.0
    for b, h in zip(base, rated):
        h["p_win"] = round(b / s, 4)


def compute_ev(rated: list[dict]) -> None:
    for h in rated:
        h["ev_win"] = round(h["p_win"] * h["odds_win"], 3)
        h["edge"] = round(h["p_win"] - h["q_win"], 4)


def assign_popularity(rated: list[dict]) -> None:
    """オッズ昇順で人気を採番（収集側に無くても必ず入るように）。"""
    for rank, h in enumerate(sorted(rated, key=lambda x: x["odds_win"]), start=1):
        h["popularity"] = rank


def assign_marks(rated: list[dict]) -> None:
    """印は『実力+騎手スコア(ability_prob)』の降順で付ける（◎○▲△＝本命/対抗/単穴/連下）。
    方針(b): proofで検証した生の実力+騎手prob順位をそのまま◎にする。
    ability_prob が無い馬（enrichのdegrade/取得失敗）は末尾に回す。
    全馬に ability_prob が無ければ p_win 降順にフォールバック（予想は必ず出る）。"""
    have_ability = any(h.get("ability_prob") is not None for h in rated)
    if have_ability:
        # ability_prob がある馬を優先（降順）、無い馬はp_win降順で後ろに
        def key(h):
            a = h.get("ability_prob")
            return (0, -a) if a is not None else (1, -h.get("p_win", 0))
        order = sorted(rated, key=key)
    else:
        order = sorted(rated, key=lambda x: -x.get("p_win", 0))  # フォールバック=従来挙動
    for i, h in enumerate(order):
        h["_prank"] = i + 1
        h["mark"] = MARKS[i][0] if i < len(MARKS) else ""


def build_reasons(h: dict) -> list[str]:
    """根拠（2〜3行）。強さ→市場比較とEV→（あれば）近走の実力評価。"""
    ev = h["ev_win"]
    edge_pt = round(h["edge"] * 100, 1)
    pop = h.get("popularity", "?")
    ab = h.get("ability_prob")
    if ab is not None:
        line1 = f"実力+騎手スコア {ab*100:.1f}%・{h['_prank']}番手評価"
    else:
        line1 = f"予想勝率 {h['p_win']*100:.1f}%・{h['_prank']}番手評価"
    if ev >= EV_THRESHOLD:
        line2 = f"{pop}番人気 / EV {ev}（理論上プラス＝妙味 {edge_pt:+.1f}pt）"
    elif edge_pt <= -1.0:
        line2 = f"{pop}番人気 / EV {ev}（やや過剰人気・妙味なし）"
    else:
        line2 = f"{pop}番人気 / EV {ev}（控除率の壁で理論上マイナス）"
    reasons = [line1, line2]

    feat = h.get("features")
    if feat and feat.get("n_runs"):
        bits = []
        if feat.get("best_agari"):
            bits.append(f"上がり最速{feat['best_agari']}")
        if feat.get("style"):
            bits.append(feat["style"])
        if feat.get("dist_surface_fit"):
            bits.append(f"当条件近走{feat['dist_surface_fit']}走")
        tilt = h.get("_form_tilt")
        note = ""
        if tilt and tilt >= 1.05:
            note = "（実力で上積み評価）"
        elif tilt and tilt <= 0.95:
            note = "（実力面はやや割引）"
        if bits:
            reasons.append("近走: " + " / ".join(bits) + note)
    return reasons


def assign_hidden_picks(rated: list[dict]) -> list[int]:
    """検証済みの指標Aをそのまま商品化: 『実力+騎手top3 ∩ 人気4番手以下』＝隠れ複勝候補。
    proofと同一定義（evaluable=n_data>=3 の中で ability_prob 上位3頭、そのうち人気4+）。
    4週288R実証: 複勝率26.3%（ベースライン12.4%）/ 複勝回収110.2%。
    ability_n_data が無い馬（旧enrich/degrade）は対象外に落ちるだけで安全。"""
    ev = [h for h in rated if h.get("ability_prob") is not None
          and (h.get("ability_n_data") or 0) >= HIDDEN_MIN_DATA]
    top3 = sorted(ev, key=lambda h: -h["ability_prob"])[:3]
    picks = []
    for rank, h in enumerate(top3, start=1):
        if h.get("popularity", 0) >= 4:
            h["hidden_pick"] = True
            h["reasons"].append(
                f"隠れ複勝候補: 実力+騎手{rank}番手評価なのに{h['popularity']}番人気"
                f"（市場の見落とし筋・検証で複勝率2倍超）")
            picks.append(h["umaban"])
    return picks


def build_tickets(rated: list[dict]) -> list[dict]:
    """買い目候補：EV≧しきい値の単勝のみ（妙味）。無ければ空＝見送り。"""
    vals = sorted([h for h in rated if h["ev_win"] >= EV_THRESHOLD],
                  key=lambda x: -x["ev_win"])
    return [{
        "type": "単勝", "target": str(h["umaban"]), "ev": h["ev_win"], "stake_unit": 1,
        "note": f"{h['_prank']}番手評価・妙味 +{round(h['edge']*100,1)}pt",
    } for h in vals]


def build_race_prediction(race: dict) -> dict:
    horses = race.get("horses", [])
    rated = [h for h in horses if h.get("odds_win") and h["odds_win"] > 1.0]
    unrated = [h for h in horses if not (h.get("odds_win") and h["odds_win"] > 1.0)]

    overround = 1.0
    tickets: list[dict] = []
    hidden: list[int] = []
    if rated:
        overround = market_devig(rated)
        estimate_p(rated)
        compute_ev(rated)
        assign_popularity(rated)
        assign_marks(rated)
        for h in rated:
            h["reasons"] = build_reasons(h)
        hidden = assign_hidden_picks(rated)
        tickets = build_tickets(rated)
        for h in rated:
            h.pop("_prank", None)
            h.pop("_form_tilt", None)

    for h in unrated:
        h.update({"q_win": 0, "p_win": 0, "ev_win": 0, "edge": 0,
                  "mark": "", "reasons": ["オッズ無し（出走取消の可能性）"]})

    takeout_pct = round((overround - 1.0) * 100)
    if hidden:
        hidden_note = f"隠れ複勝候補: {'・'.join(str(u) + '番' for u in hidden)}。 "
    else:
        hidden_note = ""
    if tickets:
        value_note = f"妙味のある馬 {len(tickets)}頭（EV≧{EV_THRESHOLD}）。"
    else:
        value_note = (f"EV>1の馬なし。控除率 約{takeout_pct}%の壁で、"
                      f"オッズだけでは妙味は出にくい回。妙味の面では見送り目線。")

    return {
        **{k: race.get(k) for k in
           ("race_id", "date", "track", "race_no", "race_name",
            "distance_m", "surface", "going")},
        "updated_at": datetime.now(JST).isoformat(timespec="seconds"),
        "market_overround": round(overround, 3),
        "value_note": hidden_note + value_note,
        "hidden_picks": hidden,
        "horses": horses,
        "tickets": tickets,
    }


def demo_race() -> dict:
    """サンプル（人気〜穴まで。穴に◎が付かない/EVが暴れないことを確認できる）。"""
    return {
        "race_id": "20260621_tokyo_11",
        "date": "2026-06-21", "track": "東京", "race_no": 11,
        "race_name": "サンプルステークス", "distance_m": 1600,
        "surface": "芝", "going": "良",
        "horses": [
            {"umaban": 3,  "name": "テンプレキング", "jockey": "C.ルメール", "odds_win": 2.8},
            {"umaban": 7,  "name": "バリューボルト", "jockey": "戸崎圭太",  "odds_win": 4.5},
            {"umaban": 1,  "name": "ハイポップ",     "jockey": "川田将雅",  "odds_win": 6.0},
            {"umaban": 10, "name": "ロングショット", "jockey": "横山武史",  "odds_win": 8.5},
            {"umaban": 5,  "name": "ミドルレンジ",   "jockey": "横山典弘",  "odds_win": 11.0},
            {"umaban": 12, "name": "ダークホース",   "jockey": "松山弘平",  "odds_win": 18.0},
            {"umaban": 8,  "name": "アウトサイダー", "jockey": "鮫島克駿",  "odds_win": 30.0},
            {"umaban": 4,  "name": "ロングオッズ",   "jockey": "（見習）",  "odds_win": 120.0},
        ],
    }


def main():
    ap = argparse.ArgumentParser(description="カチウマ 分析エンジン (Phase 2)")
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
            print("入力が無いため --demo 相当で動作します")
            races = [demo_race()]
        else:
            for f in files:
                races.extend(json.loads(f.read_text(encoding="utf-8")))

    index = []
    for race in races:
        pred = build_race_prediction(race)
        out = outdir / f"{pred['race_id']}.json"
        out.write_text(json.dumps(pred, ensure_ascii=False, indent=2), encoding="utf-8")
        honma = next((h for h in pred["horses"] if h.get("mark") == "◎"), None)
        best_ev = max((h.get("ev_win", 0) for h in pred["horses"]), default=0)
        index.append({
            "race_id": pred["race_id"], "date": pred["date"], "track": pred["track"],
            "race_no": pred["race_no"], "race_name": pred["race_name"],
            "best_mark_umaban": honma["umaban"] if honma else None,
            "best_ev": best_ev,
            "value_count": len(pred["tickets"]),
            "hidden_count": len(pred.get("hidden_picks", [])),
        })

    index.sort(key=lambda r: (str(r["track"]), r["race_no"] or 0))
    (outdir / "index.json").write_text(
        json.dumps({"updated_at": datetime.now(JST).isoformat(timespec="seconds"),
                    "races": index}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  wrote {len(index)} races -> {outdir}")


if __name__ == "__main__":
    main()
