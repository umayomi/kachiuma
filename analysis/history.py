#!/usr/bin/env python3
"""
カチウマ — 履歴DB（Phase 4-2 / 特徴量の土台）

結果ページの集計から「条件別の成績」を貯める。
生のレース結果をそのまま保存せず、(馬/騎手 × 条件) ごとの
出走・勝・連対・複勝の回数（＝derivedな集計値）として持つ。
これを縮小付きの複勝率などに変換して特徴量に使う。

保存先（data/history/）:
  horse_stats.json   { horse_id: {name, dims:{dimkey:{st,w,p,s}}, agari:{n,rank_sum}} }
  jockey_stats.json  { jockey:   {dimkey:{st,w,p,s}} }
  meta.json          { seen:[race_id...], n_races:int }

dimkey 例:
  "course=東京|芝|1800|左"   同コース
  "sd=芝|1800"               芝/ダ×距離
  "dir=左"                   回り
  "going=良"                 馬場状態

縮小(ベイズ): rate = (hits + K*base) / (st + K)  少走では基準値へ寄る。
"""

from __future__ import annotations
import json
from pathlib import Path

WIN_BASE = 0.08    # 基準勝率(おおよそ1/12)
TOP3_BASE = 0.25   # 基準複勝率(おおよそ3/12)
K = 4              # 縮小の強さ(出走Kでちょうど基準と半々)


def _blank() -> dict:
    return {"st": 0, "w": 0, "p": 0, "s": 0}


def blank_db() -> dict:
    return {"horse": {}, "jockey": {}, "meta": {"seen": [], "n_races": 0}}


def _dimkeys(race: dict) -> list[str]:
    t, sf = race.get("track"), race.get("surface")
    d, dr, g = race.get("distance_m"), race.get("direction"), race.get("going")
    keys = []
    if t and sf and d:
        keys.append(f"course={t}|{sf}|{d}|{dr or '?'}")
    if sf and d:
        keys.append(f"sd={sf}|{d}")
    if dr:
        keys.append(f"dir={dr}")
    if g:
        keys.append(f"going={g}")
    return keys


def _bump(cell: dict, fin: int) -> None:
    cell["st"] += 1
    if fin == 1:
        cell["w"] += 1
    if fin <= 2:
        cell["p"] += 1
    if fin <= 3:
        cell["s"] += 1


def ingest_race(db: dict, race: dict) -> bool:
    """1レースの結果を集計に反映。既知のrace_idはスキップ。"""
    rid = race.get("race_id")
    if not rid or rid in db["meta"]["seen"]:
        return False
    horses = [h for h in race.get("horses", []) if h.get("finish_pos")]
    if not horses:
        return False
    dimkeys = _dimkeys(race)
    # 上がり順位（レース内で速い順=1位）
    ag_sorted = sorted([h for h in horses if h.get("agari")], key=lambda x: x["agari"])
    agari_rank = {id(h): i + 1 for i, h in enumerate(ag_sorted)}

    for h in horses:
        fin = h["finish_pos"]
        hid = h.get("horse_id")
        if hid:
            hs = db["horse"].setdefault(
                hid, {"name": h.get("name"), "dims": {}, "agari": {"n": 0, "rank_sum": 0}})
            for k in dimkeys:
                _bump(hs["dims"].setdefault(k, _blank()), fin)
            r = agari_rank.get(id(h))
            if r:
                hs["agari"]["n"] += 1
                hs["agari"]["rank_sum"] += r
        jk = h.get("jockey")
        if jk:
            js = db["jockey"].setdefault(jk, {})
            for k in dimkeys:
                if k.startswith("course=") or k.startswith("sd="):
                    _bump(js.setdefault(k, _blank()), fin)
    db["meta"]["seen"].append(rid)
    db["meta"]["n_races"] += 1
    return True


def rate(cell: dict | None, kind: str = "s", base: float = TOP3_BASE, k: int = K):
    """縮小付きの率。kind: w=勝率 / p=連対率 / s=複勝率。データ無→None。"""
    if not cell or cell["st"] == 0:
        return None
    return round((cell[kind] + k * base) / (cell["st"] + k), 3)


# ---- 取得ヘルパ -------------------------------------------------------
def horse_cell(db: dict, horse_id: str, dimkey: str) -> dict | None:
    h = db["horse"].get(horse_id)
    return h["dims"].get(dimkey) if h else None


def horse_course_rate(db, horse_id, race, kind="s"):
    return rate(horse_cell(db, horse_id, f"course={race.get('track')}|{race.get('surface')}"
                           f"|{race.get('distance_m')}|{race.get('direction') or '?'}"), kind)


def horse_sd_rate(db, horse_id, race, kind="s"):
    return rate(horse_cell(db, horse_id, f"sd={race.get('surface')}|{race.get('distance_m')}"), kind)


def horse_dir_rate(db, horse_id, race, kind="s"):
    dr = race.get("direction")
    return rate(horse_cell(db, horse_id, f"dir={dr}"), kind) if dr else None


def horse_going_rate(db, horse_id, race, kind="s"):
    g = race.get("going")
    return rate(horse_cell(db, horse_id, f"going={g}"), kind) if g else None


def horse_avg_agari_rank(db, horse_id):
    h = db["horse"].get(horse_id)
    if not h or h["agari"]["n"] == 0:
        return None
    return round(h["agari"]["rank_sum"] / h["agari"]["n"], 2)


def horse_total_starts(db, horse_id) -> int:
    """そのDB内での総出走数（dir=各セルのstの和＝1走で必ず1つ計上される）。"""
    h = db["horse"].get(horse_id)
    if not h:
        return 0
    return sum(c["st"] for k, c in h["dims"].items() if k.startswith("dir="))


def jockey_course_rate(db, jockey, race, kind="s"):
    js = db["jockey"].get(jockey)
    if not js:
        return None
    key = f"course={race.get('track')}|{race.get('surface')}|{race.get('distance_m')}|{race.get('direction') or '?'}"
    return rate(js.get(key), kind)


# ---- 入出力 -----------------------------------------------------------
def load_db(dirpath: str | Path) -> dict:
    d = Path(dirpath)
    db = blank_db()
    for name, key in (("horse_stats.json", "horse"),
                      ("jockey_stats.json", "jockey"),
                      ("meta.json", "meta")):
        f = d / name
        if f.exists():
            db[key] = json.loads(f.read_text(encoding="utf-8"))
    return db


def save_db(db: dict, dirpath: str | Path) -> None:
    d = Path(dirpath)
    d.mkdir(parents=True, exist_ok=True)
    (d / "horse_stats.json").write_text(json.dumps(db["horse"], ensure_ascii=False), encoding="utf-8")
    (d / "jockey_stats.json").write_text(json.dumps(db["jockey"], ensure_ascii=False), encoding="utf-8")
    (d / "meta.json").write_text(json.dumps(db["meta"], ensure_ascii=False), encoding="utf-8")


# ---- 自己テスト -------------------------------------------------------
if __name__ == "__main__":
    db = blank_db()
    race1 = {"race_id": "R1", "track": "東京", "surface": "芝", "distance_m": 1800,
             "direction": "左", "going": "良", "horses": [
                 {"horse_id": "H1", "name": "アルファ", "finish_pos": 1, "jockey": "J1", "agari": 33.2},
                 {"horse_id": "H2", "name": "ベータ",  "finish_pos": 2, "jockey": "J2", "agari": 34.0},
                 {"horse_id": "H3", "name": "ガンマ",  "finish_pos": 5, "jockey": "J1", "agari": 35.1},
             ]}
    race2 = {"race_id": "R2", "track": "東京", "surface": "芝", "distance_m": 1800,
             "direction": "左", "going": "良", "horses": [
                 {"horse_id": "H1", "name": "アルファ", "finish_pos": 3, "jockey": "J1", "agari": 33.5},
                 {"horse_id": "H2", "name": "ベータ",  "finish_pos": 1, "jockey": "J2", "agari": 33.0},
             ]}
    assert ingest_race(db, race1)
    assert ingest_race(db, race2)
    assert not ingest_race(db, race1)  # 重複スキップ
    print("n_races:", db["meta"]["n_races"])
    print("H1 同コース複勝率(縮小):", horse_course_rate(db, "H1", race1))   # 2/2 → 縮小で<1
    print("H1 上がり平均順位:", horse_avg_agari_rank(db, "H1"))            # (1+1)/2=1.0
    print("J2 同コース複勝率(縮小):", jockey_course_rate(db, "J2", race1))  # 2/2 → 縮小
    print("H3 同コース複勝率:", horse_course_rate(db, "H3", race1))         # 0/1 → 縮小で基準寄り
    # 入出力
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        save_db(db, tmp)
        db2 = load_db(tmp)
        assert db2["meta"]["n_races"] == 2
        assert db2["horse"]["H1"]["dims"]
    print("\nOK: 履歴DB(集計・縮小・入出力)健全")
