#!/usr/bin/env python3
"""db.netkeiba 馬ページ(全キャリア)取得・解析。
着順・着差・クラス・タイム指数まで取れる。重いのでキャッシュ前提で使う。
"""
import re
import time
import json
import unicodedata
from pathlib import Path
from bs4 import BeautifulSoup

HORSE_URL = "https://db.netkeiba.com/horse/{hid}/"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _z2h(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "")


def class_from_name(name: str):
    """レース名からクラス格を数値化。新馬/未勝利=1 … オープン=5 … G3=6 G2=7 G1=8。"""
    n = _z2h(name)
    level, label = None, None
    if "新馬" in n:
        level, label = 1, "新馬"
    elif "未勝利" in n:
        level, label = 1, "未勝利"
    elif re.search(r"1勝", n) or "500万" in n:
        level, label = 2, "1勝クラス"
    elif re.search(r"2勝", n) or "1000万" in n:
        level, label = 3, "2勝クラス"
    elif re.search(r"3勝", n) or "1600万" in n:
        level, label = 4, "3勝クラス"
    elif "オープン" in n or "リステッド" in n or re.search(r"\(L\)", n):
        level, label = 5, "オープン"
    # グレード（レース名の (G1)/(GI) 等で上書き）
    if re.search(r"\(?G\s*(?:I{1,3}|[123])\)?", n):
        if re.search(r"\(?G\s*(?:III|3)\)?", n):
            level, label = 6, "G3"
        if re.search(r"\(?G\s*(?:II|2)\)?", n):
            level, label = 7, "G2"
        if re.search(r"\(?G\s*(?:I|1)\)?(?![I0-9])", n):
            level, label = 8, "G1"
    return level, label


def _surface_distance(s: str):
    s = _z2h(s)
    surface = "芝" if s.startswith("芝") else ("ダート" if s.startswith("ダ")
              else ("障害" if "障" in s else None))
    m = re.search(r"(\d{3,4})", s)
    return surface, (int(m.group(1)) if m else None)


def _to_int(s):
    s = _z2h(s)
    m = re.search(r"-?\d+", s)
    return int(m.group()) if m else None


def _to_float(s):
    s = _z2h(s)
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def parse_horse_career(html: str) -> list[dict]:
    """馬ページHTML → 過去走のリスト(新しい順)。各走に着順/着差/クラス/タイム指数等。"""
    soup = BeautifulSoup(html, "lxml")
    tbl = soup.select_one("table.db_h_race_results, table.nk_tb_common")
    if not tbl:
        return []
    rows = tbl.select("tr")
    if len(rows) < 2:
        return []
    heads = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]

    def col(name_pred):
        for i, h in enumerate(heads):
            if name_pred(h):
                return i
        return None

    i_date = col(lambda h: "日付" in h)
    i_venue = col(lambda h: h == "開催" or "開催" in h)
    i_name = col(lambda h: "レース名" in h)
    i_n = col(lambda h: "頭数" in h)
    i_odds = col(lambda h: h == "オッズ")
    i_pop = col(lambda h: "人気" in h)
    i_fin = col(lambda h: "着順" in h)
    i_jk = col(lambda h: "騎手" in h)
    i_kg = col(lambda h: "斤量" in h)
    i_dist = col(lambda h: "距離" in h)
    i_going = col(lambda h: h == "馬場")
    i_time = col(lambda h: h == "タイム")
    i_margin = col(lambda h: "着差" in h)
    i_spd = col(lambda h: "タイム指数" in h and "タイム指数M" not in h)
    i_pass = col(lambda h: "通過" in h)
    i_agari = col(lambda h: h == "上り" or "上がり" == h)
    i_bw = col(lambda h: "馬体重" in h)
    i_prize = col(lambda h: "賞金" in h)

    def g(cells, i):
        return cells[i].strip() if (i is not None and i < len(cells)) else ""

    out = []
    for tr in rows[1:]:
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if not cells:
            continue
        date = g(cells, i_date)
        if not re.match(r"\d{4}/\d{2}/\d{2}", _z2h(date)):
            continue
        name = g(cells, i_name)
        cls, cls_label = class_from_name(name)
        surface, distance_m = _surface_distance(g(cells, i_dist))
        out.append({
            "date": _z2h(date).replace("/", "-"),
            "venue": g(cells, i_venue),
            "race_name": name,
            "race_class": cls,
            "class_label": cls_label,
            "field_size": _to_int(g(cells, i_n)),
            "odds": _to_float(g(cells, i_odds)),
            "popularity": _to_int(g(cells, i_pop)),
            "finish_pos": _to_int(g(cells, i_fin)),
            "jockey": g(cells, i_jk),
            "weight_carried": _to_float(g(cells, i_kg)),
            "surface": surface,
            "distance_m": distance_m,
            "going": g(cells, i_going) or None,
            "time": g(cells, i_time) or None,
            "margin": _to_float(g(cells, i_margin)),
            "speed_index": _to_int(g(cells, i_spd)),
            "passage": g(cells, i_pass) or None,
            "agari": _to_float(g(cells, i_agari)),
            "body_weight": g(cells, i_bw) or None,
            "prize": _to_float(g(cells, i_prize)),
        })
    return out


# ---- Selenium取得（Actions上で使う。ローカル検証では呼ばない） ----
def make_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    opt = Options()
    for a in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
              "--disable-gpu", "--window-size=1280,2000", "--lang=ja-JP",
              f"--user-agent={UA}"):
        opt.add_argument(a)
    return webdriver.Chrome(options=opt)


def fetch_horse(driver, horse_id: str, wait: float = 5.0) -> list[dict]:
    driver.get(HORSE_URL.format(hid=horse_id))
    time.sleep(wait)
    return parse_horse_career(driver.page_source)


# ---- キャッシュ（取った馬は二度取らない） ----
def load_cache(path: str) -> dict:
    p = Path(path)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def save_cache(path: str, cache: dict):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    # 診断で得たベルファストの1行を忠実に再現して解析を検証
    head = ("<tr>" + "".join(f"<th>{h}</th>" for h in [
        "日付","開催","天気","R","レース名","映像","頭数","枠番","馬番","オッズ","人気",
        "着順","騎手","斤量","距離","水分量","馬場","馬場指数","タイム","着差",
        "タイム指数(通常)","タイム指数M","スタート指数","追走指数","上がり指数","通過","ペース",
        "上り","馬体重","厩舎コメント","備考","勝ち馬(2着馬)","賞金"]) + "</tr>")
    row = ("<tr>" + "".join(f"<td>{c}</td>" for c in [
        "2026/05/10","1新潟4","晴","12","4歳以上1勝クラス","","13","7","10","3.2","1",
        "3","河原田菜","52","芝1200","","良","-10","1:09.9","0.2",
        "74","65","85","74","91","2-2","35.1-34.6","34.7","498(+2)","","","ジェニファー","210.0"]) + "</tr>")
    html = f'<table class="db_h_race_results">{head}{row}</table>'
    rec = parse_horse_career(html)[0]
    print("クラス:", rec["race_class"], rec["class_label"], "(期待 2/1勝クラス)")
    print("着順:", rec["finish_pos"], "/ 着差:", rec["margin"], "/ 頭数:", rec["field_size"])
    print("芝ダ:", rec["surface"], "距離:", rec["distance_m"], "/ 馬場:", rec["going"])
    print("タイム指数:", rec["speed_index"], "/ 上がり:", rec["agari"], "/ 人気:", rec["popularity"])
    assert rec["race_class"] == 2 and rec["finish_pos"] == 3 and rec["margin"] == 0.2
    assert rec["surface"] == "芝" and rec["distance_m"] == 1200 and rec["speed_index"] == 74
    print("\nOK: 馬ページ解析 健全")
