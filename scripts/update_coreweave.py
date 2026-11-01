#!/usr/bin/env python3
"""Check CoreWeave's PUBLIC investor news, respecting robots.txt and refusals.

Only exact future financial-results conference-call dates disclosed in an
official release are added to events.json. No guessing, no CAPTCHA bypass.
This is a low-frequency public-page checker, not a realtime earnings feed.
"""
import datetime as dt
import html
from html.parser import HTMLParser
import json
import re
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data/events.json"
BASE="https://investors.coreweave.com"
NEWS=BASE+"/news/"
USER_AGENT="InvestorCalendar/1.0 (public IR calendar check; github.com/tatsuyaiwasaki1231-star/investor-calendar)"
JST=ZoneInfo("Asia/Tokyo")
ET=ZoneInfo("America/New_York")
MAX_BYTES=2_000_000

class NewsLinks(HTMLParser):
 def __init__(self):
  super().__init__();self.urls=set()
 def handle_starttag(self,tag,attrs):
  if tag!="a":return
  address=dict(attrs).get("href","")
  u=urllib.parse.urljoin(BASE,address)
  p=urllib.parse.urlsplit(u)
  if p.netloc!="investors.coreweave.com" or p.scheme!="https":return
  if re.search(r"/news/news-details/20\d\d/",p.path,re.I) and re.search(r"date.*(?:financial-results|earnings)",p.path,re.I):
   self.urls.add(urllib.parse.urlunsplit((p.scheme,p.netloc,p.path,"","")))

def read_url(url):
 request=urllib.request.Request(url,headers={"User-Agent":USER_AGENT,"Accept":"text/html"})
 with urllib.request.urlopen(request,timeout=20) as response:
  if response.status!=200:raise RuntimeError("HTTP "+str(response.status))
  b=response.read(MAX_BYTES+1)
 if len(b)>MAX_BYTES:raise ValueError("Response exceeds size limit")
 return b.decode("utf-8",errors="replace")

def robots_allowed():
 robot=urllib.robotparser.RobotFileParser()
 robot.set_url(BASE+"/robots.txt")
 # Unavailable robots policy => skip rather than bypassing access limits
 robot.read()
 return robot.can_fetch(USER_AGENT,NEWS)

def disclosed_call(html_data,url):
 text=re.sub(r"(?is)<(script|style)\b.*?</\1>"," ",html_data)
 text=html.unescape(re.sub(r"(?s)<[^>]*>"," ",text))
 text=re.sub(r"\s+"," ",text)
 # Do not use published article dates, quarters, inferred earnings windows, etc.
 pat=(r"(?:quarterly\s+conference\s+call|earnings\s+conference\s+call)"
      r".{0,250}?\bon\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
      r"(January|February|March|April|May|June|July|August|September|October|November|December)"
      r"\s+(\d{1,2}),?\s+(20\d\d)\s+at\s+(\d{1,2}):(\d{2})\s*(AM|PM)"
      r"\s+(?:Eastern\s+Time|ET)\b")
 m=re.search(pat,text,re.I)
 if not m:return None
 month,day,year,h,minutes,ampm=m.groups()
 local=dt.datetime.strptime(f"{month.title()} {day} {year} {h}:{minutes} {ampm.upper()}","%B %d %Y %I:%M %p").replace(tzinfo=ET)
 jst=local.astimezone(JST)
 if not dt.datetime.now(JST)-dt.timedelta(days=2)<=jst<=dt.datetime.now(JST)+dt.timedelta(days=450):
  return None
 return {
  "id":"crwv-official-"+local.date().isoformat(),
  "date":jst.date().isoformat(),
  "time":jst.strftime("%H:%M"),
  "marketDate":local.date().isoformat(),
  "title":"★ CoreWeave 決算説明会（公式IR確認）",
  "symbol":"CRWV","region":"US","category":"earnings","importance":"high",
  "confidence":"confirmed","sourceName":"CoreWeave公式IRニュース",
  "sourceUrl":url,
  "detail":"CoreWeave公式発表の決算説明会日時を米東部時間から日本時間へ変換。決算資料の公開時刻とは異なる場合があります。",
  "timeLabel":"説明会 "+jst.strftime("%H:%M")+" JST",
  "automated":True
 }

def main():
 content=json.loads(DATA.read_text(encoding="utf-8"))
 statuses=content.setdefault("dataStatus",{})
 try:
  if not robots_allowed():
   raise RuntimeError("robots.txtで許可が確認できないためチェックを見送り")
  raw=read_url(NEWS)
  links=NewsLinks();links.feed(raw)
  candidates=sorted(links.urls,reverse=True)[:6]
  if not candidates:
   raise RuntimeError("公式ニュース一覧に決算日告知リンクを検出できず")
  extracted=[]
  for url in candidates:
   try:
    val=disclosed_call(read_url(url),url)
    if val:extracted.append(val)
   except Exception as exc:
    print("Could not retrieve an official release:",type(exc).__name__,str(exc)[:120])
  if not extracted:raise RuntimeError("決算日時の本文確認に成功せず（既存予定は維持）")
  added=0
  for e in extracted:
   existing=next((x for x in content["events"] if x.get("symbol")=="CRWV" and x.get("date")==e["date"] and x.get("category")=="earnings"),None)
   if existing:
    # Source can be enriched without discarding existing descriptions
    if not existing.get("sourceUrl"):
     existing["sourceUrl"]=e["sourceUrl"]
    continue
   content["events"].append(e);added+=1
  statuses["coreweave"]=f"公式発表確認 {len(extracted)}件・新規登録 {added}件"
  content["lastCoreWeaveCheckAt"]=dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
  print(statuses["coreweave"])
 except Exception as exc:
  statuses["coreweave"]="公式IR取得未完了（既存日程を保持）"
  print("CoreWeave check unavailable; no bypass:",type(exc).__name__,str(exc)[:250])
 content["events"].sort(key=lambda e:(e.get("date",""),e.get("time",""),e.get("id","")))
 DATA.write_text(json.dumps(content,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

if __name__=="__main__":main()
