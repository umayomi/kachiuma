name: debug-shutuba
on: workflow_dispatch
jobs:
  dbg:
    runs-on: ubuntu-latest
    steps:
      - run: pip install requests beautifulsoup4 lxml
      - name: inspect
        run: |
          python - << 'PY'
          import requests
          from bs4 import BeautifulSoup
          rid = "202602010211"
          ua = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
          url = f"https://race.netkeiba.com/race/result.html?race_id={rid}"
          html = requests.get(url, headers=ua, timeout=20).text
          print("LEN", len(html), "has HorseList:", "HorseList" in html)
          soup = BeautifulSoup(html, "lxml")
          rows = soup.select("tr.HorseList")
          print("HorseList rows:", len(rows))
          if rows:
              row = rows[0]
              print("tds:", len(row.select("td")))
              for i, td in enumerate(row.select("td")):
                  print(i, td.get("class"), "|", td.get_text(strip=True)[:14])
          PY
