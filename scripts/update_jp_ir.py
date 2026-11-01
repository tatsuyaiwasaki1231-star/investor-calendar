#!/usr/bin/env python3
"""Conservative Japanese earnings calendar checker, from company IR pages only.

No JPX bulk redistribution, scraping of login/paywall services, access-control
bypass, or guessed dates. One polite GET per allowed first-party source,
once per day (plus push/manual tests). Ignore incomplete month-only schedules.
On conflicts preserve the existing event and require human verification.
"""
import datetime as dt
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data/events.json"
JST=ZoneInfo("Asia/Tokyo")
AGENT="InvestorCalendar/1.0 (personal IR date checker; github.com/tatsuyaiwasaki1231-star/investor-calendar)"
SOURCE=[
 ("8035","東京エレクトロン","https://www.tel.co.jp/ir/calendar/"),
 ("6146","ディスコ","https://www.disco.co.jp/jp/ir/calendar/"),
 ("9984","ソフトバンクグループ","https://group.softbank/ir/calendar"),
 ("6134","FUJI","https://www.fuji.co.jp/ir/calendar.html"),
 ("4186","東京応化工業","https://www.tok.co.jp/ir/calender"),
 ("6479","ミネベアミツミ","https://www.minebeamitsumi.com/corp/investors/calendar/"),
 ("6857","アドバンテスト","https://www.advantest.com/ja/investors/ir-calendar/"),
 ("7735","SCREEN","https://www.screen.co.jp/ir/calendar"),
 ("6723","ルネサス","https://www.renesas.com/jp/ja/about/investor-relations"),
 ("6981","村田製作所","https://corporate.murata.com/ja-jp/ir/calendar"),
 ("6963","ローム","https://www.rohm.co.jp/ir/stock/calendar"),
 ("4063","信越化学工業","https://www.shinetsu.co.jp/jp/ir/ir-calendar/"),
 ("6525","KOKUSAI ELECTRIC","https://www.kokusai-electric.com/ir/calendar"),
 ("4047","関東電化工業","https://www.kantodenka.co.jp/ir/calendar/"),
 ("285A","キオクシアホールディングス","https://www.kioxia-holdings.com/ja-jp/ir.html"),
 ("3436","SUMCO","https://www.sumcosi.com/ir/event/calendar.html"),
]
# Only full dates next to 決算発表. An adjacent 2027年3月期 does not
# give us the announcement date unless a separate complete date appears.
FULL_DATE=re.compile(r"(?P<year>20(?:26|27|28))(?:\s*年\s*(?P<mj>0?[1-9]|1[0-2])\s*月\s*(?P<dj>0?[1-9]|[12]\d|3[01])\s*日|[./-](?P<mi>0?[1-9]|1[0-2])[./-](?P<di>0?[1-9]|[12]\d|3[01])(?!\d))")
QUARTER=re.compile(r"第\s*([1-4])\s*四半期|(?:中間期)|(?:本決算)|(?:通期決算)")
NOW=dt.datetime.now(JST).date()

class VisibleText(HTMLParser):
 def __init__(self):
  super().__init__(convert_charrefs=True);self.parts=[];self.skip=0
 def handle_starttag(self,tag,attrs):
  if tag in ("script","style","noscript"):self.skip+=1
  if not self.skip and tag in ("div","p","tr","td","h1","h2","h3","h4","li","dd","dt","br","section"):
   self.parts.append(" ")
 def handle_endtag(self,tag):
  if tag in ("script","style","noscript"):self.skip=max(0,self.skip-1)
  elif not self.skip and tag in ("div","p","tr","td","h1","h2","h3","h4","li","dd","dt"):
   self.parts.append(" ")
 def handle_data(self,data):
  if not self.skip:self.parts.append(data)
 def text(self):
  return re.sub(r"\s+"," ","".join(self.parts))

def request_text(url,timeout=8,maxsize=1_400_000):
 req=urllib.request.Request(url,headers={"User-Agent":AGENT,"Accept":"text/html,text/plain"})
 with urllib.request.urlopen(req,timeout=timeout) as res:
  if res.status!=200:raise ValueError("HTTP "+str(res.status))
  if res.geturl().split("/")[2].lower()!=urllib.parse.urlsplit(url).hostname.lower():
   raise ValueError("Cross-host redirect not allowed")
  body=res.read(maxsize+1)
  charset=res.headers.get_content_charset() or "utf-8"
 if len(body)>maxsize:raise ValueError("Too much page content")
 return body.decode(charset,errors="replace")

def robots_ok(url):
 p=urllib.parse.urlsplit(url)
 origin=p.scheme+"://"+p.netloc
 try:
  raw=request_text(origin+"/robots.txt",timeout=6,maxsize=180_000)
  parser=urllib.robotparser.RobotFileParser()
  parser.parse(raw.splitlines())
  return parser.can_fetch(AGENT,url), "robots.txt"
 except urllib.error.HTTPError as e:
  if e.code==404:return True,"robots.txt=404 (no explicit rules)"
  return False,"robots unreadable HTTP "+str(e.code)
 except Exception as e:
  return False,"robots unreadable: "+type(e).__name__

def important_quarter(snippet):
 match=QUARTER.search(snippet)
 if match:
  return "Q"+match.group(1) if match.group(1) else ("中間" if "中間" in match.group(0) else "通期")
 return ""

def candidates(text,url,symbol,name):
 events=[]
 for m in FULL_DATE.finditer(text):
  # Date must be immediately followed by a declared scheduled earnings announcement.
  next_date=FULL_DATE.search(text,m.end(),min(len(text),m.end()+115))
  cut=next_date.start() if next_date else min(len(text),m.end()+115)
  tail=text[m.end():cut]
  pos=tail.find("決算発表")
  if pos<0:continue
  before=tail[:pos+4]
  if "決算日" in before and not QUARTER.search(before):continue
  q=important_quarter(before)
  if not q:continue
  try:date=dt.date(int(m.group("year")),int(m.group("mj") or m.group("mi")),int(m.group("dj") or m.group("di")))
  except ValueError:continue
  if not NOW-dt.timedelta(days=1)<=date<=NOW+dt.timedelta(days=390):continue
  # Avoid turning an annual schedule's quarter/month into an exact day.
  if "予定" not in tail[:pos+30] and "決算発表" not in tail:continue
  events.append((date.isoformat(),q))
 return list(dict.fromkeys(events))

def main():
 # Only the 19:05 JST scheduled run performs company website requests.
 # A push/manual dispatch immediately tests updated code.
 if os.getenv("GITHUB_EVENT_NAME")=="schedule" and dt.datetime.now(dt.timezone.utc).hour==22:
  print("Japan company calendar run skipped in morning to limit polling")
  return
 data=json.loads(DATA.read_text(encoding="utf-8"))
 status=[]
 seen=0;added=0
 for symbol,name,url in SOURCE:
  try:
   allowed,robots=robots_ok(url)
   if not allowed:
    status.append({"symbol":symbol,"name":name,"state":"skipped","reason":robots})
    print("JP IR skip:",symbol,robots);continue
   raw=request_text(url)
   parser=VisibleText()
   parser.feed(raw)
   found=candidates(parser.text(),url,symbol,name)
   seen+=1
   new=0
   for date,quarter in found:
    # Preserve any manually verified schedule, including its exact time.
    existing=[e for e in data["events"] if e.get("symbol")==symbol and
       e.get("category")=="earnings" and e.get("date")==date]
    if existing:continue
    # A different future date for the same quarter may be a schedule change.
    # Do not silently overwrite or duplicate it.
    conflicts=[e for e in data["events"] if e.get("symbol")==symbol and
       e.get("category")=="earnings" and e.get("date","")>=NOW.isoformat() and
       quarter in ("Q1","Q2","Q3","Q4") and
       (quarter in str(e.get("title","")) or
       ("第"+quarter[1]+"四半期") in str(e.get("title",""))) and
       abs((dt.date.fromisoformat(e["date"])-dt.date.fromisoformat(date)).days)<150]
    if conflicts:
     status.append({"symbol":symbol,"name":name,"state":"needs_review",
       "reason":"同じ四半期で別の日程が登録済み","candidateDate":date})
     continue
    entry={"id":"jp-ir-"+symbol+"-"+date,"date":date,"time":"",
       "marketDate":date,"title":name+" "+quarter+" 決算発表予定（公式IR日付）",
       "symbol":symbol,"region":"JP","category":"earnings","importance":"high",
       "confidence":"scheduled","sourceName":name+"公式IRカレンダー",
       "sourceUrl":url,"detail":"企業公式IRカレンダーの将来の決算発表予定日を確認。時刻は未確認。日程変更があり得ます。",
       "timeLabel":"発表時刻未確認","automated":True}
    data["events"].append(entry)
    new+=1;added+=1
   status.append({"symbol":symbol,"name":name,"state":"ok","fullDates":len(found),"newEvents":new})
   print("JP IR checked:",symbol,"full future dates:",len(found),"added:",new)
  except Exception as exc:
   status.append({"symbol":symbol,"name":name,"state":"unavailable","reason":type(exc).__name__+": "+str(exc)[:90]})
   print("JP IR unavailable (no bypass):",symbol,type(exc).__name__,str(exc)[:90])
 data["events"].sort(key=lambda e:(e.get("date",""),e.get("time",""),e.get("id","")))
 data.setdefault("dataStatus",{})["japanOfficialIR"]=f"IRページ取得成功 {seen}/{len(SOURCE)}社、新規日程{added}件（要確認は別途）"
 data["japanIRSources"]=status
 data["japanIRCheckedAt"]=dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
 DATA.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(data["dataStatus"]["japanOfficialIR"])
if __name__=="__main__":main()
