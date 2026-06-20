#!/usr/bin/env python3
"""
カチウマ — netkeiba 取得・解析の低レベル層（Phase 1）

役割:
  - find_race_ids(date)     : ある開催日(YYYYMMDD)の全 race_id を取得
  - parse_shutuba(...)       : 出馬表を構造化（馬番/馬名/性齢/騎手/オッズ/人気）
  - get_win_odds(race_id)    : 単勝オッズをAPIから取得（人気はオッズ順で算出）
  - parse_result(...)        : レース結果（着順/タイム/上がり）
  - parse_horse_pastruns(...): 各馬の過去走（直近N走）

注意（重要）:
  netkeiba の HTML/エンドポイントは変わることがある。各セレクタは「壊れる前提」で、
  取れなかった項目は None にして WARNING ログを出す（黙って失敗しない）。
  実HTMLでの初回検証が必要（ビルド環境からは netkeiba に到達できないため未検証）。
"""

from __future__ import annotations
import json
import logging
import re
import time

import requests
from bs4 import BeautifulSoup

log = logging.getLogger("netkeiba")

BASE_RACE = "https://race.netkeiba.com"
BASE_DB = "https://db.netkeiba.com"

HEADERS = {
    # netkeibaは非ブラウザUAやiPhone UAだと簡易ページを返すため、PC版Chrome相当を名乗る
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept-Language": "ja,en;q=0.8",
}
INTERVAL_SEC = 1.5  # アクセス間隔（負荷をかけない）

# 競馬場コード(race_idの5-6桁目) -> 名称
TRACK = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
    "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉",
}


def get(url: str, retries: int = 3, timeout: int = 20) -> str:
    """負荷をかけないGET。リトライ・指数バックオフ・適切なエンコーディング。"""
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            # db.netkeiba は EUC-JP、race.netkeiba は UTF-8
            r.encoding = "euc-jp" if "db.netkeiba.com" in url else "utf-8"
            time.sleep(INTERVAL_SEC)
            return r.text
        except Exception as e:  # noqa
            last = e
            log.warning("GET失敗(%d/%d) %s : %s", i + 1, retries, url, e)
            time.sleep(INTERVAL_SEC * (i + 1))
    raise last


# ----------------------------------------------------------------------
# レースID探索
# ----------------------------------------------------------------------
def find_race_ids(date: str) -> list[str]:
    """開催日(YYYYMMDD)の全 race_id(12桁) を返す。非開催日は空。"""
    url = f"{BASE_RACE}/top/race_list_sub.html?kaisai_date={date}"
    try:
        html = get(url)
    except Exception:
        log.error("レース一覧の取得に失敗: %s", date)
        return []
    ids = set(re.findall(r"race_id=(\d{12})", html))
    out = sorted(ids)
    log.info("%s: race_id %d件", date, len(out))
    return out


# ----------------------------------------------------------------------
# 出馬表
# ----------------------------------------------------------------------
def _race_header(soup: BeautifulSoup, race_id: str) -> dict:
    track = TRACK.get(race_id[4:6], "")
    race_no = int(race_id[-2:])
    name = _text(soup.select_one(".RaceName")) or _text(soup.select_one(".RaceList_Item02 .RaceName"))
    data01 = _text(soup.select_one(".RaceData01"))
    distance_m, surface, going = _parse_data01(data01)
    return {
        "race_id": race_id,
        "date": f"{race_id[0:4]}-??-??",  # 正確な月日はrace_listから補完してもよい
        "track": track,
        "race_no": race_no,
        "race_name": name,
        "distance_m": distance_m,
        "surface": surface,
        "going": going,
    }


def _parse_data01(text: str) -> tuple[int | None, str | None, str | None]:
    """ '芝1600m' / '馬場:良' などから 距離・馬場種別・状態 を抽出。"""
    if not text:
        return None, None, None
    surface = None
    if "芝" in text:
        surface = "芝"
    elif "ダ" in text:
        surface = "ダート"
    elif "障" in text:
        surface = "障害"
    m = re.search(r"(\d{3,4})m", text)
    distance = int(m.group(1)) if m else None
    g = re.search(r"馬場\s*[:：]\s*(良|稍重|重|不良)", text)
    going = g.group(1) if g else None
    return distance, surface, going


def parse_shutuba(html: str, race_id: str, odds_map: dict[int, float] | None = None) -> dict:
    """出馬表HTMLを構造化。odds_map があれば単勝オッズ・人気を付与。"""
    soup = BeautifulSoup(html, "lxml")
    race = _race_header(soup, race_id)
    horses: list[dict] = []

    rows = soup.select("tr.HorseList")
    if not rows:
        log.warning("出馬表の行(tr.HorseList)が見つからない: %s", race_id)

    for tr in rows:
        # 馬番クラスは枠番が後ろに付く(Umaban1, Umaban2…)ので前方一致で取る
        umaban = _to_int(_text(tr.select_one("td[class^='Umaban']")))
        a = tr.select_one("td.HorseInfo a[href*='/horse/']") or tr.select_one(".HorseName a")
        name = _text(a)
        horse_id = None
        if a and a.has_attr("href"):
            hm = re.search(r"/horse/(\d+)", a["href"])
            horse_id = hm.group(1) if hm else None
        sex_age = _text(tr.select_one("td.Barei"))
        # 斤量は専用クラスが無く、性齢(Barei)の次のtd
        barei_td = tr.select_one("td.Barei")
        weight_carried = _to_float(_text(barei_td.find_next_sibling("td"))) if barei_td else None
        jockey = _text(tr.select_one("td.Jockey a")) or _text(tr.select_one("td.Jockey"))
        trainer = _text(tr.select_one("td.Trainer"))
        horse_weight = _text(tr.select_one("td.Weight"))  # 例 "468(+10)"

        h = {
            "umaban": umaban,
            "name": name,
            "horse_id": horse_id,
            "sex_age": sex_age,
            "jockey": jockey,
            "trainer": trainer,
            "weight_carried": weight_carried,
            "horse_weight": horse_weight,
            "odds_win": None,
            "popularity": None,
        }
        if odds_map and umaban in odds_map:
            h["odds_win"] = odds_map[umaban]
        if umaban is not None and name:
            horses.append(h)

    # オッズが付いていれば人気をオッズ昇順で算出
    rated = [h for h in horses if h["odds_win"]]
    for rank, h in enumerate(sorted(rated, key=lambda x: x["odds_win"]), start=1):
        h["popularity"] = rank

    race["horses"] = horses
    log.info("出馬表 %s: %d頭 (オッズ付与 %d頭)", race_id, len(horses), len(rated))
    return race


def get_win_odds(race_id: str) -> dict[int, float]:
    """単勝オッズをAPIから取得。{馬番: オッズ}。失敗時は空。"""
    url = f"{BASE_RACE}/api/api_get_jra_odds.html?race_id={race_id}&type=1&action=init"
    out: dict[int, float] = {}
    try:
        data = json.loads(get(url))
        odds = (data.get("data") or {}).get("odds") or {}
        win = odds.get("1") or {}  # "1" = 単勝
        for uma, arr in win.items():
            try:
                out[int(uma)] = float(arr[0])
            except (ValueError, TypeError, IndexError):
                continue
    except Exception as e:  # noqa
        log.warning("単勝オッズAPI失敗 %s : %s", race_id, e)
    return out


# ----------------------------------------------------------------------
# 結果
# ----------------------------------------------------------------------
def parse_result(html: str, race_id: str) -> dict:
    """結果HTMLから 着順/馬番/馬名/タイム/上がり/オッズ/人気 を抽出。"""
    soup = BeautifulSoup(html, "lxml")
    race = _race_header(soup, race_id)
    rows = soup.select("tr.HorseList") or soup.select("table.RaceTable01 tr")
    results = []
    for tr in rows:
        rank = _to_int(_text(tr.select_one(".Result_Num")) or _text(tr.select_one("td.Rank")))
        umaban = _to_int(_text(tr.select_one("td.Umaban")))
        name = _text(tr.select_one(".Horse_Name a")) or _text(tr.select_one("td.Horse_Name"))
        time_s = _text(tr.select_one(".Time .RaceTime")) or _text(tr.select_one("td.Time"))
        if umaban is None and rank is None:
            continue
        results.append({"rank": rank, "umaban": umaban, "name": name, "time": time_s})
    race["results"] = results
    log.info("結果 %s: %d頭", race_id, len(results))
    return race


# ----------------------------------------------------------------------
# 過去走（馬ごと）
# ----------------------------------------------------------------------
def parse_horse_pastruns(html: str, horse_id: str, n: int = 5) -> list[dict]:
    """db.netkeiba.com/horse/{id} の成績表から直近n走を抽出。"""
    soup = BeautifulSoup(html, "lxml")
    table = soup.select_one("table.db_h_race_results") or soup.select_one("table.nk_tb_common")
    runs: list[dict] = []
    if not table:
        log.warning("過去走テーブルが見つからない: horse %s", horse_id)
        return runs
    for tr in table.select("tr")[1:]:  # ヘッダ除く
        tds = [_text(td) for td in tr.select("td")]
        if len(tds) < 12:
            continue
        runs.append({
            "date": tds[0],          # 日付
            "track": tds[1],         # 開催
            "race_name": tds[4] if len(tds) > 4 else None,
            "rank": _to_int(tds[11]) if len(tds) > 11 else None,  # 着順(列位置は要検証)
        })
        if len(runs) >= n:
            break
    return runs


# ----------------------------------------------------------------------
# ユーティリティ
# ----------------------------------------------------------------------
def _text(el) -> str | None:
    if el is None:
        return None
    return re.sub(r"\s+", " ", el.get_text(strip=True)) or None


def _to_int(s):
    try:
        return int(re.sub(r"[^\d-]", "", s)) if s else None
    except (ValueError, TypeError):
        return None


def _to_float(s):
    try:
        return float(re.sub(r"[^\d.]", "", s)) if s else None
    except (ValueError, TypeError):
        return None
