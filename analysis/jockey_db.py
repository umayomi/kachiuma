#!/usr/bin/env python3
"""騎手力モジュール: umarengod の騎手集計(etcsrch4.php)をPOSTで引く。
「騎手 × 同距離 × 全場 × 直近3年(指定日の前日まで)」の複勝率を縮小付きで返す。
- リーク防止: 各レース日Dについて (D-3年)〜(D前日) で集計する
- 同条件はキャッシュして二度引かない
- 列位置(確定): [1]騎手名 [5]出走回数 [8]複勝率
"""
import re
import json
import datetime
from pathlib import Path

URL = "https://umarengod.com/etcsrch4.php"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

TOP3_BASE = 0.25   # 基準複勝率（馬側と揃える）
K = 8              # 騎手は薄い条件もあるので縮小をやや強めに

# 結果テーブルの列インデックス（診断で確定）
COL_NAME, COL_STARTS, COL_PLACE_RATE = 1, 5, 8


def _surface_param(surface: str) -> str:
    return "ダ" if (surface and "ダ" in surface) else "芝"


def period_3y(race_date: str):
    """race_date(YYYYMMDD)を基準に、(D-3年)〜(D前日)のfrom/toを返す。リーク防止。"""
    d = datetime.datetime.strptime(race_date, "%Y%m%d").date()
    end = d - datetime.timedelta(days=1)         # 前日まで（当日を含めない）
    start = d.replace(year=d.year - 3)
    return start, end


def _payload(surface: str, distance_m: int, race_date: str, place: str = "ALL") -> dict:
    s, e = period_3y(race_date)
    return {
        "fld": "kisyu", "go": "集　計",
        "yy1": str(s.year), "mm1": str(s.month), "dd1": str(s.day),
        "yy2": str(e.year), "mm2": str(e.month), "dd2": str(e.day),
        "place": place, "crs": _surface_param(surface),
        "i1": str(distance_m), "i1_e": str(distance_m),
        "course2": "ALL", "rc": "ALL", "grade": "ALL",
        "rec": "", "hn": "", "birthyear": "", "seni": "1",
        "val": "", "sort": "", "next": "",
    }


def parse_table(html: str) -> dict:
    """結果HTML → {騎手名: {"starts": int, "place_rate": float}}"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    best, n = None, -1
    for t in soup.find_all("table"):
        txt = t.get_text()
        if ("複勝率" in txt and "出走回数" in txt and "騎手名" in txt):
            rows = t.find_all("tr")
            if len(rows) > n:
                best, n = t, len(rows)
    out = {}
    if not best:
        return out
    for tr in best.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all("td")]
        if len(cells) <= COL_PLACE_RATE:
            continue
        name = cells[COL_NAME]
        if not name or "騎手" in name:   # ヘッダ行など
            continue
        starts = _to_int(cells[COL_STARTS])
        pr = _to_float(cells[COL_PLACE_RATE])
        if starts is None or pr is None:
            continue
        out[_norm_name(name)] = {"starts": starts, "place_rate": pr}
    return out


def _to_int(s):
    m = re.search(r"\d+", s or "")
    return int(m.group()) if m else None


def _to_float(s):
    m = re.search(r"\d*\.\d+|\d+", s or "")
    return float(m.group()) if m else None


def _norm_name(name: str) -> str:
    """「C.ルメール」「Ｃ．ルメール」等の表記ゆれを吸収して姓を残す。"""
    n = re.sub(r"\s+", "", name or "")
    n = n.replace("．", ".").replace("　", "")
    n = n.lstrip("▲△☆★◇◎○")   # 見習い斤量マーク等を除去（▲小林美→小林美）
    # 「X.ルメール」→「ルメール」 / 「武豊」→「武豊」
    m = re.match(r"^[A-Za-zＡ-Ｚ]+\.(.+)$", n)
    return m.group(1) if m else n


# ---- 取得（Actions上で使う。requestsのみ・軽量） ----
def fetch(session, surface: str, distance_m: int, race_date: str, place: str = "ALL"):
    """1条件ぶんPOSTして、テーブル全体(騎手→成績)を返す。placeで競馬場 or ALL。"""
    r = session.post(URL, data=_payload(surface, distance_m, race_date, place),
                     headers={"User-Agent": UA}, timeout=40)
    r.encoding = r.apparent_encoding
    return parse_table(r.text)


def lookup(table: dict, jockey: str):
    """結果ページの騎手名(省略形)で umarengod テーブル(フルネーム)を引く。
    姓の前方一致で吸収（例: 川田→川田将雅, 横山武→横山武史）。"""
    key = _norm_name(jockey)
    if not key:
        return None
    if key in table:
        return table[key]
    cands = [(k, v) for k, v in table.items() if k.startswith(key) or key.startswith(k)]
    if len(cands) == 1:
        return cands[0][1]
    if cands:  # 複数該当は出走数最多（＝著名騎手）を採用
        return max(cands, key=lambda kv: kv[1]["starts"])[1]
    return None


MIN_STARTS = 5   # 場×距離をそのまま信用する最低戦数。4戦以下は全場×距離へ


def resolve(place_tbl: dict, all_tbl: dict, jockey: str, min_starts: int = MIN_STARTS):
    """5戦以上→場×距離、4戦以下→全場×距離 にフォールバック。
    戻り: (cell or None, source文字列)"""
    pc = lookup(place_tbl, jockey) if place_tbl else None
    if pc and pc["starts"] >= min_starts:
        return pc, "場×距離"
    ac = lookup(all_tbl, jockey) if all_tbl else None
    if ac:
        return ac, "全場×距離(F)"
    return None, "なし"


def rate(cell, base=TOP3_BASE, k=K):
    """縮小付き複勝率。cell={"starts","place_rate"} or None。"""
    if not cell or not cell.get("starts"):
        return None
    st, pr = cell["starts"], cell["place_rate"]
    return (pr * st + base * k) / (st + k)


# ---- キャッシュ（条件キー: place|surface|distance|period_end） ----
def cache_key(surface: str, distance_m: int, race_date: str, place: str = "ALL") -> str:
    s, e = period_3y(race_date)
    return f"{place}|{_surface_param(surface)}|{distance_m}|{e.isoformat()}"


def load_cache(path: str) -> dict:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_cache(path: str, cache: dict):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    # 期間生成(リーク防止)とパースをオフライン検証
    s, e = period_3y("20260531")
    print("期間:", s, "〜", e, "(期待: 2023-05-31 〜 2026-05-30)")
    assert s == datetime.date(2023, 5, 31) and e == datetime.date(2026, 5, 30)

    pl = _payload("芝", 2400, "20260531", place="東京")
    print("POST例:", {k: pl[k] for k in ("fld", "yy1", "yy2", "place", "crs", "i1", "i1_e")})
    assert pl["i1"] == pl["i1_e"] == "2400" and pl["place"] == "東京" and pl["crs"] == "芝"

    # 診断で得たヘッダ+ルメール行を再現してパース検証
    head = "".join(f"<td>{h}</td>" for h in
                   ["No.", "騎手名", "1着回数", "2着回数", "3着回数", "出走回数",
                    "勝率", "連対率", "複勝率", "単勝回収率", "複勝回収率"])
    row = "".join(f"<td>{c}</td>" for c in
                  ["1", "C.ルメール", "4", "8", "7", "25", ".160", ".480", ".760", "31%", "107%"])
    html = f'<table><tr>{head}</tr><tr>{row}</tr></table>'
    tbl = parse_table(html)
    print("パース結果:", tbl)
    assert tbl["ルメール"]["starts"] == 25 and tbl["ルメール"]["place_rate"] == 0.76
    r = rate(tbl["ルメール"])
    print(f"縮小複勝率: {r:.3f} (生.760 → 出走25で {r:.3f})")
    print("姓正規化:", _norm_name("Ｃ．ルメール"), _norm_name("武豊"))

    # 姓の前方一致マッチング検証（結果ページの省略形 → umarengodフルネーム）
    full = {"川田将雅": {"starts": 44, "place_rate": 0.545},
            "横山武史": {"starts": 30, "place_rate": 0.40},
            "横山典弘": {"starts": 10, "place_rate": 0.30},
            "武豊": {"starts": 35, "place_rate": 0.457}}
    assert lookup(full, "川田")["starts"] == 44, "川田→川田将雅"
    assert lookup(full, "横山武")["starts"] == 30, "横山武→横山武史"
    assert lookup(full, "武豊")["starts"] == 35, "武豊→武豊(完全一致)"
    print("姓マッチング: 川田→川田将雅 / 横山武→横山武史 / 武豊→武豊  OK")

    # フォールバック検証（場×距離が薄い→全場へ）
    place_tbl = {"川田将雅": {"starts": 3, "place_rate": 0.667}}   # 場×距離 3戦(薄い)
    all_tbl = {"川田将雅": {"starts": 44, "place_rate": 0.545}}     # 全場×距離 44戦
    cell, src = resolve(place_tbl, all_tbl, "川田")
    print(f"川田: {src} starts={cell['starts']} (3戦→全場フォールバック期待)")
    assert src.startswith("全場") and cell["starts"] == 44
    place_tbl2 = {"川田将雅": {"starts": 8, "place_rate": 0.50}}    # 場×距離 8戦(十分)
    cell2, src2 = resolve(place_tbl2, all_tbl, "川田")
    assert src2 == "場×距離" and cell2["starts"] == 8
    print(f"川田(場8戦): {src2} starts={cell2['starts']} (5戦以上→場採用)")
    print("\nOK: 騎手力モジュール 健全（場×距離/フォールバック/姓マッチング）")
