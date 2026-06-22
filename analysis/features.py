#!/usr/bin/env python3
"""
カチウマ — 実力スコア（Phase 4-2）

履歴DB(history.py)から各馬の「オッズと独立した実力スコア」を作り、
レース内で正規化して実力prob を出す。これを市場prob(q)と突き合わせ、
「過小評価(妙味) / 過剰人気 / オッズ通り強い」を見分けるのが目的。

特徴量（すべて縮小付きの複勝率＝少走では基準寄り）:
  course   同コース(競馬場×芝ダ×距離×回り)の複勝率
  sd       芝ダ×距離の複勝率
  dir      回り(右/左)の複勝率
  going    馬場状態の複勝率
  jk_course 騎手の同コース複勝率
  agari_rank 過去の上がり3F順位の平均(小さいほど末脚が速い)

注意: 重みは暫定。必ずウォークフォワードのバックテストで採否を判定する。
"""

from __future__ import annotations
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import history as H  # noqa: E402

BASE = H.TOP3_BASE   # 基準複勝率
BETA = 2.5           # 実力スコア→確率の鋭さ(温度)

# 各特徴量の重み（基準からの上振れにかける）
WEIGHTS = {
    "course": 1.0,
    "sd": 0.8,
    "dir": 0.4,
    "going": 0.4,
    "jk_course": 0.6,
}


def horse_features(db: dict, race: dict, h: dict) -> dict:
    hid = h.get("horse_id")
    today_cls = race.get("race_class")            # 今日の格(1〜8) or None
    avg_top3_cls = H.horse_avg_top3_class(db, hid) if hid else None
    avg_cls = H.horse_avg_class(db, hid) if hid else None
    return {
        "course": H.horse_course_rate(db, hid, race) if hid else None,
        "sd": H.horse_sd_rate(db, hid, race) if hid else None,
        "dir": H.horse_dir_rate(db, hid, race) if hid else None,
        "going": H.horse_going_rate(db, hid, race) if hid else None,
        "jk_course": H.jockey_course_rate(db, h.get("jockey"), race),
        "agari_rank": H.horse_avg_agari_rank(db, hid) if hid else None,
        "n_data": H.horse_total_starts(db, hid) if hid else 0,
        # クラス: 着内実績のクラスが今日と同等以上か（複勝率の“相手の強さ”を補正）
        "class_edge": (avg_top3_cls - today_cls)
        if (avg_top3_cls is not None and today_cls) else None,
        # クラス: 普段より楽な格に降りてきたか（降級=プラス）
        "class_drop": (avg_cls - today_cls)
        if (avg_cls is not None and today_cls) else None,
        # 着差: 勝ち馬からの平均馬身（小さいほど競っている）
        "margin": H.horse_avg_margin(db, hid) if hid else None,
        "today_class": today_cls,
    }


# クラス・着差の暫定重み（必ずバックテストで採否判定）
W_CLASS_EDGE = 0.15   # 今日と同等以上のクラスで着内実績 → 加点
W_CLASS_DROP = 0.10   # 降級(普段より楽) → 加点
W_MARGIN = 0.05       # 勝ち馬から近い競馬 → 加点
MARGIN_BASE = 3.0     # この馬身を基準に、近ければ+/大敗なら-


def ability_raw(feat: dict) -> float:
    """基準からの上振れの重み付け和。データ無しは0(=中立)。"""
    s = 0.0
    for k, w in WEIGHTS.items():
        v = feat.get(k)
        if v is not None:
            s += w * (v - BASE)
    ar = feat.get("agari_rank")
    if ar is not None:
        s += 0.04 * (6.0 - ar)   # 上がり順位が上位(小さい)ほど加点
    ce = feat.get("class_edge")
    if ce is not None:
        s += W_CLASS_EDGE * math.tanh(ce)        # 上のクラスで好走=+, 下級でしか=−
    cd = feat.get("class_drop")
    if cd is not None:
        s += W_CLASS_DROP * math.tanh(cd)        # 降級=+, 昇級=−
    mg = feat.get("margin")
    if mg is not None:
        s += W_MARGIN * max(-1.0, min(1.0, (MARGIN_BASE - mg) / MARGIN_BASE))
    return s


def ability_probs(db: dict, race: dict):
    """レース内で正規化した実力prob を返す。
    returns (probs_by_umaban, feats_by_umaban, raw_by_umaban)
    """
    horses = race.get("horses", [])
    feats, raws = {}, {}
    for h in horses:
        f = horse_features(db, race, h)
        feats[h["umaban"]] = f
        raws[h["umaban"]] = ability_raw(f)
    exps = {u: math.exp(BETA * v) for u, v in raws.items()}
    tot = sum(exps.values()) or 1.0
    probs = {u: e / tot for u, e in exps.items()}
    return probs, feats, raws


if __name__ == "__main__":
    # 合成DBで動作確認: 同コース実績が濃い馬の実力probが上がるか
    db = H.blank_db()
    course_race = {"race_id": "X", "track": "東京", "surface": "芝", "distance_m": 1800,
                   "direction": "左", "going": "良"}
    # H1=同コース3戦3好走の実力馬, H2=同コース未勝利, H3=データ薄
    for i in range(3):
        H.ingest_race(db, {**course_race, "race_id": f"T{i}", "horses": [
            {"horse_id": "H1", "name": "実力馬", "finish_pos": 1, "jockey": "J1", "agari": 33.0},
            {"horse_id": "H2", "name": "凡走馬", "finish_pos": 8, "jockey": "J2", "agari": 35.5},
        ]})
    target = {**course_race, "race_id": "TARGET", "horses": [
        {"umaban": 1, "name": "実力馬", "horse_id": "H1", "jockey": "J1"},
        {"umaban": 2, "name": "凡走馬", "horse_id": "H2", "jockey": "J2"},
        {"umaban": 3, "name": "新規馬", "horse_id": "H9", "jockey": "J9"},
    ]}
    probs, feats, raws = ability_probs(db, target)
    for u in (1, 2, 3):
        print(f"馬{u} 実力prob={probs[u]*100:5.1f}%  raw={raws[u]:+.3f}  "
              f"course={feats[u]['course']} agari順={feats[u]['agari_rank']}")
    assert probs[1] > probs[3] > probs[2], "実力馬 > 新規馬 > 凡走馬 になるはず"
    print("\nOK: 実力スコア(実績の濃い馬を高く評価)健全")
