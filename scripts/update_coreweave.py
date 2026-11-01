#!/usr/bin/env python3
"""Track public Business Wire RSS for company-issued CoreWeave earnings alerts.

- No investor email registration, no SEC user-agent impersonation.
- Does not visit a blocked CoreWeave IR host.
- Downloads one public industry-neutral Business Wire RSS feed per run.
- Creates earnings calendar events ONLY when an issuer news release states
  a specific future conference-call date, time and Eastern timezone.
- News headlines and earnings dates are separate concepts.
"""
import datetime as dt
import html
import json
import re
from pathlib import Path
import urllib.request
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data/events.json"
IR=ROOT/"data/ir_notices.json"
RSS="https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJcFVJYWQ=="
USER_AGENT="InvestorCalendar/1.0 (low-frequency public RSS reader; github.com/tatsuyaiwasaki1231-star/investor-calendar)"
ET_ZONE=ZoneInfo("America/New_York")
JST=ZoneInfo("Asia/Tokyo")
DATE_PATTERN=(r"(?:quarterly\s+conference\s+call|earnings\s+conference\s+call)"
 r".{0,300}?\bon\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
 r"(January|February|March|April|May|June|July|August|September|October|November|December)"
 r"\s+(\d{1,2}),?\s+(20\d\d)\s+at\s+(\d{1,2}):(\d{2})\s*(AM|PM)"
 r"\s+(?:Eastern\s+Time|ET)\b")

def get_text(url,max_bytes=9_000_000):
 p=urlsplit(url)
 if p.scheme!="https" or p.hostname not in ("feed.businesswire.com","www.businesswire.com","businesswire.com"):
  raise ValueError("Non-approved newswire host")
 req=urllib.request.Request(url,headers={"User-Agent":USER_AGENT,"Accept":"application/rss+xml,application/xml,text/html"})
 with urllib.request.urlopen(req,timeout=20) as r:
  if r.status!=200:raise ValueError(f"HTTP {r.status}")
  body=r.read(max_bytes+1)
 if len(body)>max_bytes:raise ValueError("Feed size exceeds limit")
 return body.decode("utf-8-sig",errors="replace")

def cleaned(x):
 x=re.sub(r"(?is)<(script|style)\b.*?</\1>"," ",x)
 x=html.unescape(re.sub(r"(?s)<[^>]*>"," ",x))
 return re.sub(r"\s+"," ",x)

def read_rss():
 root=ET.fromstring(get_text(RSS))
 articles=[]
 for item in root.iter():
  if item.tag.rsplit("}",1)[-1]!="item":continue
  title=next((x.text or "" for x in item if x.tag.rsplit("}",1)[-1]=="title"),"").strip()
  if not re.search(r"\bcoreweave\b",title,re.I):continue
  link=next((x.text or "" for x in item if x.tag.rsplit("}",1)[-1]=="link"),"").strip()
  if not link.startswith("https://") or urlsplit(link).hostname not in ("www.businesswire.com","businesswire.com"):continue
  if not re.search(r"(financial results|quarter|earnings|senior notes|debt|financing|offering|loan)",title,re.I):continue
  desc=next((x.text or "" for x in item if x.tag.rsplit("}",1)[-1]=="description"),"")
  pub=next((x.text or "" for x in item if x.tag.rsplit("}",1)[-1]=="pubDate"),"")
  articles.append({"title":title,"link":link,"description":desc,"pubDate":pub})
 return articles[:20]

def parse_date(text,link):
 m=re.search(DATE_PATTERN,cleaned(text),re.I)
 if not m:return None
 mo,day,year,hh,minute,am=m.groups()
 eastern=dt.datetime.strptime(f"{mo.title()} {day} {year} {hh}:{minute} {am.upper()}","%B %d %Y %I:%M %p").replace(tzinfo=ET_ZONE)
 japanese=eastern.astimezone(JST)
 now=dt.datetime.now(JST)
 if not now-dt.timedelta(days=2)<=japanese<=now+dt.timedelta(days=425):return None
 return {"id":"crwv-wire-"+eastern.date().isoformat(),
 "date":japanese.date().isoformat(),"time":japanese.strftime("%H:%M"),"marketDate":eastern.date().isoformat(),
 "title":"★ CoreWeave 決算説明会（企業発表を確認）","symbol":"CRWV",
 "region":"US","category":"earnings","importance":"high","confidence":"confirmed",
 "sourceName":"CoreWeave発表／Business Wire配信","sourceUrl":link,
 "detail":"CoreWeave発表の決算説明会日時を米東部時間から日本時間に変換。記事公開日ではありません。",
 "timeLabel":"説明会 "+japanese.strftime("%H:%M")+" JST","automated":True}

def main():
 data=json.loads(DATA.read_text(encoding="utf-8"))
 status=data.setdefault("dataStatus",{})
 try:
  hits=read_rss()
  added=0;headlines=[]
  for item in hits:
   title=item["title"]
   if not title.lower().startswith("coreweave"):continue
   # "Official" designation requires explicit issuer name and a newswire article.
   if re.search(r"(announces date|to report|will report).*(?:financial results|earnings)",title,re.I):
    excerpt=item["description"]
    if not re.search(DATE_PATTERN,cleaned(excerpt),re.I):
     try:excerpt=get_text(item["link"],max_bytes=2_000_000)
     except Exception as exc:
      print("Newswire detail unavailable, no bypass:",str(exc)[:140])
    event=parse_date(excerpt,item["link"])
    if event and not any(e.get("symbol")=="CRWV" and e.get("category")=="earnings" and e.get("date")==event["date"] for e in data["events"]):
     data["events"].append(event);added+=1
   headlines.append({"company":"CoreWeave","symbol":"CRWV","title":title[:180],
    "articlePublishedDate":"","sourceName":"CoreWeave企業発表／Business Wire配信",
    "sourceUrl":item["link"],"kind":"ir-news-not-earnings-date"})
  if IR.exists():
   ir=json.loads(IR.read_text(encoding="utf-8"))
   prev=ir.get("notices",[])
   unique={x.get("sourceUrl"):x for x in (headlines+prev) if x.get("sourceUrl")}
   ir["notices"]=list(unique.values())[:25]
   ir["coreweaveSourceStatus"]="RSS取得成功・該当見出し"+str(len(headlines))+"件"
   IR.write_text(json.dumps(ir,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
  status["coreweave"]="Business Wire RSS取得成功・新規決算"+str(added)+"件"
  data["lastCoreWeaveCheckAt"]=dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
  print(status["coreweave"])
 except Exception as exc:
  status["coreweave"]="Business Wire RSS取得失敗・登録済み予定を維持"
  print("Business Wire RSS unavailable; no bypass:",type(exc).__name__,str(exc)[:250])
 data["events"].sort(key=lambda e:(e.get("date",""),e.get("time",""),e.get("id","")))
 DATA.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
if __name__=="__main__":main()
