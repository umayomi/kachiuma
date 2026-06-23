#!/usr/bin/env python3
"""全キャリア(db.netkeiba 馬ページ)から実力スコアを算出。
各レースで「その日より前のキャリアだけ」を使うのでリークしない。
材料は従来と同じ（コース/距離/回り/馬場の複勝率＋クラス＋着差）。窓ではなく全キャリアから。
"""
import math
from datetime import datetime

TOP3_BASE = 0.25     # 基準複勝率
K = 4                # 縮小の強さ
BETA = 2.5           # softmaxの鋭さ
WEIGHTS = {"course": 1.0, "sd": 0.8, "dir": 0.4, "going": 0.4}
W_CLASS_EDGE = 0.15
W_MARGIN = 0.05
MARGIN_BASE = 3.0

TRACKS = ["札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"]
DIRECTION = {"東京": "左", "中京": "左", "新潟": "左",
             "中山": "右", "京都": "右", "阪神": "右", "札幌": "右",
             "函館": "右", "福島": "右", "小倉": "右"}


def _track_of(venue: str):
    for t in TRACKS:
        if venue and t in venue:
            return t
    return None


def _ymd(s: str):
    s = (s or "").replace("/", "-")
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def career_before(career: list, race_date: str) -> list:
    """race_date(YYYYMMDD)より前の出走だけ返す（リーク防止）。"""
    d0 = datetime.strptime(race_date, "%Y%m%d").date()
    out = []
    for r in career:
        d = _ymd(r.get("date"))
        if d and d < d0 and r.get("finish_pos"):
            out.append(r)
    return out


def _rate(st: int, top3: int):
    return (top3 + K * TOP3_BASE) / (st + K) if st else None


def features_from_career(past: list, today: dict) -> dict:
    """today: surface/distance_m/track/direction/going/race_class を持つ今日のレース条件。"""
    surf, dist = today.get("surface"), today.get("distance_m")
    tdir, going = today.get("direction"), today.get("going")
    tcls = today.get("race_class")

    def rate_where(pred):
        st = top3 = 0
        for r in past:
            if pred(r):
                st += 1
                if r["finish_pos"] <= 3:
                    top3 += 1
        return _rate(st, top3)

    course = rate_where(lambda r: _track_of(r.get("venue")) == today.get("track")
                        and r.get("surface") == surf and r.get("distance_m") == dist)
    sd = rate_where(lambda r: r.get("surface") == surf and r.get("distance_m") == dist)
    dr = rate_where(lambda r: DIRECTION.get(_track_of(r.get("venue"))) == tdir)
    go = rate_where(lambda r: r.get("going") == going)

    top3_cls = [r["race_class"] for r in past
                if r["finish_pos"] <= 3 and r.get("race_class")]
    class_edge = (sum(top3_cls) / len(top3_cls) - tcls) if (top3_cls and tcls) else None

    behind = [max(0.0, r["margin"]) for r in past if r.get("margin") is not None]
    margin = (sum(behind) / len(behind)) if behind else None

    return {"course": course, "sd": sd, "dir": dr, "going": go,
            "class_edge": class_edge, "margin": margin, "n_data": len(past)}


def ability_raw(feat: dict) -> float:
    s = 0.0
    for k, w in WEIGHTS.items():
        v = feat.get(k)
        if v is not None:
            s += w * (v - TOP3_BASE)
    ce = feat.get("class_edge")
    if ce is not None:
        s += W_CLASS_EDGE * math.tanh(ce)
    mg = feat.get("margin")
    if mg is not None:
        s += W_MARGIN * max(-1.0, min(1.0, (MARGIN_BASE - mg) / MARGIN_BASE))
    return s


def ability_probs(careers: dict, race: dict, race_date: str):
    """careers: {umaban: 全キャリアlist}, race: 今日の条件+horses。
    戻り: (probs{umaban:p}, feats{umaban:feat})"""
    feats, raws = {}, {}
    for h in race["horses"]:
        u = h["umaban"]
        past = career_before(careers.get(u, []), race_date)
        feats[u] = features_from_career(past, race)
        raws[u] = ability_raw(feats[u])
    mx = max(raws.values()) if raws else 0.0
    exps = {u: math.exp(BETA * (r - mx)) for u, r in raws.items()}
    tot = sum(exps.values()) or 1.0
    probs = {u: e / tot for u, e in exps.items()}
    return probs, feats


if __name__ == "__main__":
    # 全キャリアからの算出を検証：H1は上のクラス(3)で着内常連、H2は下級(1)でのみ着内
    def race_row(hid, fin, cls, mg, venue="1東京4", surf="芝", dist=1800, going="良"):
        return {"horse_id": hid, "finish_pos": fin, "race_class": cls, "margin": mg,
                "venue": venue, "surface": surf, "distance_m": dist, "going": going,
                "date": "2026-01-10"}
    careers = {
        1: [race_row("H1", 2, 3, 0.4) for _ in range(5)],   # 2勝クラスで2着常連
        2: [race_row("H2", 1, 1, 0.0) for _ in range(5)],   # 未勝利を勝っただけ
    }
    today = {"surface": "芝", "distance_m": 1800, "track": "東京", "direction": "左",
             "going": "良", "race_class": 3,
             "horses": [{"umaban": 1}, {"umaban": 2}]}
    probs, feats = ability_probs(careers, today, "20260601")
    for u in (1, 2):
        f = feats[u]
        print(f"馬{u} prob={probs[u]*100:5.1f}% class_edge={f['class_edge']} "
              f"course={f['course']} n={f['n_data']} margin={f['margin']}")
    assert probs[1] > probs[2], "上のクラスで好走のH1が高くなるはず"
    print("\nOK: 全キャリア実力スコア 健全（上のクラス好走を高評価）")
