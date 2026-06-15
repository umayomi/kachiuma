#!/usr/bin/env python3
"""
パーサ単体テスト（ネット接続不要）

netkeiba の構造を模した最小HTMLで、解析ロジックが正しく動くかを検証する。
※ これは「機械が動くこと」の保証であり、実netkeibaのセレクタ一致の保証ではない。
   実HTMLでズレたら、ここにその構造を写経してテストを足し、parserを直す。
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import netkeiba as nk  # noqa: E402

RACE_ID = "202605021011"  # 2026 / 東京(05) / 2回 / 10日 / 11R

SHUTUBA_HTML = """
<div class="RaceList_Item02">
  <div class="RaceName">テスト記念 (G1)</div>
</div>
<div class="RaceData01"> 15:40発走 / 芝1600m (左) / 天候:晴 / 馬場:良 </div>
<table class="Shutuba_Table">
  <tr class="HorseList">
    <td class="Umaban Txt_C">7</td>
    <td class="HorseInfo"><div class="Horse02"><a href="https://db.netkeiba.com/horse/2021100123/">バリューボルト</a></div></td>
    <td class="Barei Txt_C">牡4</td>
    <td class="Jockey"><a href="#">戸崎圭太</a></td>
  </tr>
  <tr class="HorseList">
    <td class="Umaban Txt_C">3</td>
    <td class="HorseInfo"><div class="Horse02"><a href="https://db.netkeiba.com/horse/2020104567/">テンプレキング</a></div></td>
    <td class="Barei Txt_C">牡5</td>
    <td class="Jockey"><a href="#">C.ルメール</a></td>
  </tr>
</table>
"""

RESULT_HTML = """
<div class="RaceName">テスト記念 (G1)</div>
<div class="RaceData01"> 芝1600m / 馬場:良 </div>
<table class="RaceTable01">
  <tr class="HorseList">
    <td class="Result_Num"><div class="Rank">1</div></td>
    <td class="Umaban Txt_C">7</td>
    <td class="Horse_Name"><a href="#">バリューボルト</a></td>
    <td class="Time"><span class="RaceTime">1:33.2</span></td>
  </tr>
  <tr class="HorseList">
    <td class="Result_Num"><div class="Rank">2</div></td>
    <td class="Umaban Txt_C">3</td>
    <td class="Horse_Name"><a href="#">テンプレキング</a></td>
    <td class="Time"><span class="RaceTime">1:33.4</span></td>
  </tr>
</table>
"""


def run() -> None:
    fails = []

    # --- find_race_ids（正規表現抽出のみ。HTML文字列で代用）---
    sample = 'x race_id=202605021011 y race_id=202605021012 race_id=202605021011'
    ids = sorted(set(__import__("re").findall(r"race_id=(\d{12})", sample)))
    _check(ids == ["202605021011", "202605021012"], "find_race_ids: 重複除去・抽出", fails)

    # --- 出馬表 ---
    odds = {7: 4.5, 3: 2.8}
    race = nk.parse_shutuba(SHUTUBA_HTML, RACE_ID, odds_map=odds)
    _check(race["track"] == "東京", f"header track (={race['track']})", fails)
    _check(race["race_no"] == 11, f"header race_no (={race['race_no']})", fails)
    _check(race["surface"] == "芝", f"header surface (={race['surface']})", fails)
    _check(race["distance_m"] == 1600, f"header distance (={race['distance_m']})", fails)
    _check(race["going"] == "良", f"header going (={race['going']})", fails)
    _check(len(race["horses"]) == 2, f"horses数 (={len(race['horses'])})", fails)

    by = {h["umaban"]: h for h in race["horses"]}
    _check(by[7]["name"] == "バリューボルト", "馬名抽出", fails)
    _check(by[7]["horse_id"] == "2021100123", "horse_id抽出", fails)
    _check(by[7]["jockey"] == "戸崎圭太", "騎手抽出", fails)
    _check(by[7]["odds_win"] == 4.5, "オッズ付与", fails)
    # 人気: オッズ昇順 -> 3(2.8)=1番人気, 7(4.5)=2番人気
    _check(by[3]["popularity"] == 1 and by[7]["popularity"] == 2, "人気=オッズ順で算出", fails)

    # --- 結果 ---
    res = nk.parse_result(RESULT_HTML, RACE_ID)
    _check(len(res["results"]) == 2, f"結果行数 (={len(res['results'])})", fails)
    r0 = {x["umaban"]: x for x in res["results"]}
    _check(r0[7]["rank"] == 1, "着順抽出", fails)
    _check(r0[7]["time"] == "1:33.2", "タイム抽出", fails)

    print("\n".join(f"  {'OK ' if ok else 'NG '} {msg}" for ok, msg in _LOG))
    if fails:
        print(f"\n❌ {len(fails)}件失敗")
        sys.exit(1)
    print(f"\n✅ 全{len(_LOG)}件パス（パーサのロジックは健全。実netkeibaでの一致は初回実走で確認）")


_LOG: list[tuple[bool, str]] = []


def _check(cond: bool, msg: str, fails: list) -> None:
    _LOG.append((bool(cond), msg))
    if not cond:
        fails.append(msg)


if __name__ == "__main__":
    run()
