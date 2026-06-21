#!/usr/bin/env python3
"""
カチウマ — 馬柱パーサ＆特徴量抽出（Phase 4 / 過去走）

データ源: race.netkeiba.com/race/shutuba_past.html?race_id=...
  1レースで全馬の近走（最大5走）が載る。db.netkeiba(ブロック)を避けられる。

各馬の td.Past セルから取れる項目（実HTMLで確認済み）:
  Data01: 日付 開催地 + span.Num(=R)      例 "2026.02.15 小倉 5"
  Data02: レース名 クラス                  例 "大濠特別 2勝"
  Data05: 馬場種別+距離 タイム 馬場         例 "芝1200 1:08.9 稍"
  Data03: 頭数 馬番 人気 騎手 斤量          例 "18頭 7番 1人 横山琉人 55.0"
  Data06: 通過順 (上がり3F) 馬体重          例 "6-8 (34.7) 458(-8)"
  Data07: 着差相手 (着差) + a.movie_<race_id>
  ※着順(何着)はこのページのテキストには無い → 上がり・脚質・適性で代替。

注意:
  shutuba_past には馬番列が無いため、行の並び順(=馬番順)で umaban を割り当てる。
  名前は表示用に best-effort で取得。実走ログで件数・並びを検証する前提。
"""

from __future__ import annotations
import re
from datetime import date, datetime

from bs4 import BeautifulSoup

SURFACES = {"芝": "芝", "ダ": "ダート", "障": "障害"}
GOINGS = ("良", "稍重", "稍", "重", "不良")


def _txt(el):
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)) if el else ""


def _parse_past_cell(td) -> dict | None:
    d01 = _txt(td.select_one(".Data01"))
    d05 = _txt(td.select_one(".Data05"))
    d03 = _txt(td.select_one(".Data03"))
    d06 = _txt(td.select_one(".Data06"))
    if not (d01 or d05):
        return None

    run: dict = {}
    # 日付
    m = re.search(r"(\d{4})\.(\d{2})\.(\d{2})", d01)
    run["date"] = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None
    # 過去レースID（a.movie_xxxx）
    mv = td.select_one("a[class^='movie_']")
    if mv:
        cm = re.search(r"movie_(\d+)", " ".join(mv.get("class", [])))
        run["past_race_id"] = cm.group(1) if cm else None
    # 馬場種別・距離
    run["surface"] = next((v for k, v in SURFACES.items() if k in d05), None)
    md = re.search(r"(\d{3,4})", d05)
    run["distance"] = int(md.group(1)) if md else None
    # 馬場状態
    run["going"] = next((g for g in GOINGS if g in d05), None)
    # 上がり3F（カッコ内の小数）
    ma = re.search(r"\((\d{2}\.\d)\)", d06)
    run["agari"] = float(ma.group(1)) if ma else None
    # 通過順（例 6-8）→ コーナー位置のリスト
    mp = re.search(r"(\d+(?:-\d+)+)", d06)
    run["passage"] = [int(x) for x in mp.group(1).split("-")] if mp else []
    # 頭数・人気
    mf = re.search(r"(\d+)頭", d03)
    run["field_size"] = int(mf.group(1)) if mf else None
    mpop = re.search(r"(\d+)人", d03)
    run["popularity"] = int(mpop.group(1)) if mpop else None
    return run


def parse_shutuba_past(html: str) -> list[dict]:
    """馬柱HTML → [{umaban, name, runs:[...]}]（umabanは並び順で採番）。"""
    soup = BeautifulSoup(html, "lxml")
    horses = []
    for i, tr in enumerate(soup.select("tr.HorseList"), start=1):
        a = tr.select_one("td.Horse_Info a[href*='/horse/']")
        name = _txt(a) or None
        runs = [r for td in tr.select("td.Past") if (r := _parse_past_cell(td))]
        horses.append({"umaban": i, "name": name, "runs": runs})
    return horses


# ----------------------------------------------------------------------
# 特徴量
# ----------------------------------------------------------------------
def _style_from_passage(runs: list[dict]) -> tuple[float | None, str | None]:
    """通過順から脚質を推定。最初のコーナー位置の平均割合(0=前,1=後)。"""
    ratios = []
    for r in runs:
        if r.get("passage") and r.get("field_size"):
            ratios.append(r["passage"][0] / r["field_size"])
    if not ratios:
        return None, None
    avg = sum(ratios) / len(ratios)
    label = ("逃げ・先行" if avg < 0.33 else "差し" if avg < 0.66 else "追込")
    return round(avg, 3), label


def features(horse: dict, today_distance: int | None,
             today_surface: str | None, today: date | None = None) -> dict:
    runs = horse.get("runs", [])[:5]
    today = today or date.today()

    agaris = [r["agari"] for r in runs if r.get("agari")]
    best_agari = min(agaris) if agaris else None
    avg_agari = round(sum(agaris) / len(agaris), 2) if agaris else None

    # 距離・コース適性（今回条件に近い近走の数）
    dist_fit = sum(
        1 for r in runs
        if r.get("distance") and today_distance
        and abs(r["distance"] - today_distance) <= 200
        and (today_surface is None or r.get("surface") == today_surface)
    )

    # レース間隔（直近走からの日数）
    days_since = None
    dates = [datetime.strptime(r["date"], "%Y-%m-%d").date() for r in runs if r.get("date")]
    if dates:
        days_since = (today - max(dates)).days

    style_ratio, style = _style_from_passage(runs)

    return {
        "n_runs": len(runs),
        "best_agari": best_agari,
        "avg_agari": avg_agari,
        "dist_surface_fit": dist_fit,
        "days_since_last": days_since,
        "style_ratio": style_ratio,
        "style": style,
    }


def form_score(f: dict) -> float:
    """特徴量を 0〜1 目安の素点に（高いほど好調・適性高）。
    ※暫定の重み。Phase4-2でバックテストしながら調整する。
    """
    s = 0.0
    # 上がりが速いほど加点（35.0基準、33.0で+、37.0で-）
    if f.get("best_agari"):
        s += max(-0.3, min(0.4, (35.0 - f["best_agari"]) * 0.2))
    # 今回条件に近い近走があるほど加点
    s += min(0.3, f.get("dist_surface_fit", 0) * 0.12)
    # 実戦経験（叩き2戦目以降は安定しやすい）
    s += min(0.15, max(0, f.get("n_runs", 0) - 1) * 0.05)
    return round(s, 3)


# ----------------------------------------------------------------------
if __name__ == "__main__":
    # 実HTML構造に合わせた最小fixtureで自己テスト
    FIX = """
    <tr class="HorseList">
      <td class="Waku1">1</td><td class="Waku">1</td>
      <td class="Horse_Select">印</td>
      <td class="Horse_Info"><a href="https://db.netkeiba.com/horse/2021100123/">バリューボルト</a></td>
      <td class="Jockey">牝4 横山和 56.0</td><td class="Rest">中3週</td>
      <td class="Past"><div class="Data_Item">
        <div class="Data01">2026.02.15 小倉 <span class="Num">5</span></div>
        <div class="Data02">大濠特別 2勝</div>
        <div class="Data05">芝1200 1:08.9 稍</div>
        <div class="Data03">18頭 7番 1人 横山琉 55.0</div>
        <div class="Data06">2-2 (33.4) 458(-8)</div>
        <div class="Data07">メイショウ (0.1)<a class="movie_202610010810"></a></div>
      </div></td>
      <td class="Past"><div class="Data_Item">
        <div class="Data01">2026.01.10 中山 <span class="Num">9</span></div>
        <div class="Data02">テスト 1勝</div>
        <div class="Data05">芝1400 1:21.0 良</div>
        <div class="Data03">16頭 3番 2人 横山和 55.0</div>
        <div class="Data06">5-5 (34.8) 466(+4)</div>
        <div class="Data07">ライバル (0.3)</div>
      </div></td>
    </tr>
    """
    horses = parse_shutuba_past(FIX)
    h = horses[0]
    print("馬番:", h["umaban"], "/ 名前:", h["name"], "/ 走数:", len(h["runs"]))
    for r in h["runs"]:
        print("  ", r)
    f = features(h, today_distance=1200, today_surface="芝",
                 today=date(2026, 6, 14))
    print("特徴量:", f)
    print("脚質:", _style_from_passage(h["runs"]))
    print("form_score:", form_score(f))
    assert h["runs"][0]["agari"] == 33.4
    assert h["runs"][0]["distance"] == 1200 and h["runs"][0]["surface"] == "芝"
    assert h["runs"][0]["past_race_id"] == "202610010810"
    assert f["dist_surface_fit"] == 2  # 芝1200と芝1400(±200m)で2
    print("\nOK: 馬柱パーサ・特徴量とも健全")
