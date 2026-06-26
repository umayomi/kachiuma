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
# 配点：実力の質(クラス・着差)を主役、距離帯/回り/馬場は脇役
PIVOT_CLASS = 2.6    # 質割引後クラスの中央値付近（※レース内で一定＝順位には不影響、表示用）
W_CLASS = 0.38       # 着内実績のクラス（主役を降ろし、騎手と拮抗させる）
W_MARGIN = 0.35      # 平均着差＝競った内容（主役）
W_BAND = 0.40        # 距離帯の複勝率
W_DIR = 0.20         # 回りの複勝率
W_GOING = 0.20       # 馬場の複勝率
W_JK = 0.80          # 騎手力（補助項。上位拮抗時のタイブレークに留め、本命の上書きを抑える）
CONF_C0 = 3.0        # 出走C0で信頼度0.5（少データは中立寄りに割引）
JK_C0 = 3.0          # 騎手は5戦で信頼度0.5（場×距離の薄さを踏まえやや強め）
MARGIN_BASE = 1.2    # この馬身を境に、近ければ＋・離されれば−
_QUAL = {1: 1.0, 2: 0.8, 3: 0.6}  # 着内の質（着順）。クラス実績の質割引に使う。

TRACKS = ["札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"]
DIRECTION = {"東京": "左", "中京": "左", "新潟": "左",
             "中山": "右", "京都": "右", "阪神": "右", "札幌": "右",
             "函館": "右", "福島": "右", "小倉": "右"}


def _band(d):
    """距離帯。ピンポイントでなく括りで見る（未経験距離の取りこぼしを減らす）。"""
    if not d:
        return None
    if d <= 1300:
        return "S"      # スプリント
    if d <= 1700:
        return "M"      # マイル
    if d <= 2600:
        return "C"      # 中長距離（2000の皐月賞も2400のダービーもここ）
    return "L"          # 長距離


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
    surf = today.get("surface")
    tband = _band(today.get("distance_m"))
    tdir, going = today.get("direction"), today.get("going")
    tcls = today.get("race_class")

    def rate_n(pred):
        st = top3 = 0
        for r in past:
            if pred(r):
                st += 1
                if r["finish_pos"] <= 3:
                    top3 += 1
        return _rate(st, top3), st

    band, band_n = rate_n(lambda r: r.get("surface") == surf and _band(r.get("distance_m")) == tband)
    dr, dr_n = rate_n(lambda r: DIRECTION.get(_track_of(r.get("venue"))) == tdir)
    go, go_n = rate_n(lambda r: r.get("going") == going)

    # 着内(3着内)走の「質割引クラス」: 勝ち=満点, 2着=0.8, 3着=0.6。
    # 「高い格で勝った」は残し、「高い格で3着」は割り引く（人気薄好走の過大評価を抑制）。
    top3_credit = [r["race_class"] * _QUAL[r["finish_pos"]] for r in past
                   if r.get("finish_pos") in _QUAL and r.get("race_class")]
    class_proven = (sum(top3_credit) / len(top3_credit)) if top3_credit else None
    class_edge = (class_proven - tcls) if (class_proven is not None and tcls) else None

    behind = [max(0.0, r["margin"]) for r in past if r.get("margin") is not None]
    margin = (sum(behind) / len(behind)) if behind else None

    return {"band": band, "band_n": band_n, "dir": dr, "dir_n": dr_n,
            "going": go, "going_n": go_n, "class_proven": class_proven,
            "class_edge": class_edge, "margin": margin, "n_data": len(past)}


def _conf(n):
    return n / (n + CONF_C0)


def ability_raw(feat: dict) -> float:
    return sum(ability_breakdown(feat).values())


def ability_breakdown(feat: dict) -> dict:
    """rawの各項の寄与点を返す（合計=ability_raw）。なぜこのスコアか、の分解用。"""
    parts = {"クラス": 0.0, "着差": 0.0, "距離帯": 0.0, "回り": 0.0, "馬場": 0.0, "騎手": 0.0}
    cp = feat.get("class_proven")
    if cp is not None:
        parts["クラス"] = W_CLASS * (cp - PIVOT_CLASS)
    mg = feat.get("margin")
    if mg is not None:
        parts["着差"] = W_MARGIN * max(-1.0, min(1.0, (MARGIN_BASE - mg) / MARGIN_BASE))
    for key, rate, n, w in (("距離帯", feat.get("band"), feat.get("band_n", 0), W_BAND),
                            ("回り", feat.get("dir"), feat.get("dir_n", 0), W_DIR),
                            ("馬場", feat.get("going"), feat.get("going_n", 0), W_GOING)):
        if rate is not None:
            parts[key] = w * _conf(n) * (rate - TOP3_BASE)
    jr = feat.get("jk_rate")
    if jr is not None:
        js = feat.get("jk_starts", 0)
        parts["騎手"] = W_JK * (js / (js + JK_C0)) * (jr - TOP3_BASE)
    return parts



def ability_probs(careers: dict, race: dict, race_date: str, jk_by_umaban: dict = None):
    """careers: {umaban: 全キャリアlist}, race: 今日の条件+horses。
    jk_by_umaban: {umaban: {"rate": 縮小済み複勝率, "starts": 出走数}}（騎手力・任意）
    戻り: (probs{umaban:p}, feats{umaban:feat})"""
    feats, raws = {}, {}
    for h in race["horses"]:
        u = h["umaban"]
        past = career_before(careers.get(u, []), race_date)
        feat = features_from_career(past, race)
        if jk_by_umaban and u in jk_by_umaban:
            feat["jk_rate"] = jk_by_umaban[u].get("rate")
            feat["jk_starts"] = jk_by_umaban[u].get("starts", 0)
        feats[u] = feat
        raws[u] = ability_raw(feat)
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
        print(f"馬{u} prob={probs[u]*100:5.1f}% class_proven={f['class_proven']} "
              f"band={f['band']}(n={f['band_n']}) margin={f['margin']} n={f['n_data']}")
    assert probs[1] > probs[2], "上のクラスで好走のH1が高くなるはず"
    print("\nOK: 全キャリア実力スコア 健全（上のクラス好走を高評価）")
