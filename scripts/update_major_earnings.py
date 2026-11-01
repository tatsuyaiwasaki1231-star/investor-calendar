#!/usr/bin/env python3
"""Low-frequency, public-company RSS monitor for major AI and semiconductor earnings.

Official feeds only. Never infer earnings dates from a publication timestamp,
past-year quarter number, generic "next earnings soon", or article publication date.
Date-only records use the US market calendar date; times require explicit ET.
No attempt to bypass 403, login, robots restrictions, or CAPTCHAs.
"""
import datetime as dt
import email.utils
import hashlib
import html
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data/events.json"
NEWS=ROOT/"data/ir_notices.json"
JST=ZoneInfo("Asia/Tokyo")
EASTERN=ZoneInfo("America/New_York")
AGENT="InvestorCalendar/1.0 (public RSS; github.com/tatsuyaiwasaki1231-star/investor-calendar)"
FEEDS=[
 ("AMD","AMD","https://ir.amd.com/news-events/press-releases/rss",("amd.com",)),
 ("KLA","KLAC","https://ir.kla.com/news-events/press-releases/rss",("kla.com",)),
 ("Lam Research","LRCX","https://investor.lamresearch.com/index.php?pagetemplate=rss&s=43",("lamresearch.com",)),
 ("Meta","META","https://investor.atmeta.com/rss/event.aspx",("atmeta.com",)),
 ("Meta","META","https://investor.atmeta.com/rss/pressrelease.aspx",("atmeta.com",)),
]
NEWS_RE=re.compile(r"earnings|financial results|quarterly results|earnings call|quarter.*results|results.*conference|earnings date|quarterly conference call",re.I)
FUTURE_RE=re.compile(r"to report|will report|announces? .*earnings date|sets? .*conference|to announce|will announce|earnings conference call|earnings call|results on|financial results on|results.*webcast",re.I)
MONTH_RE=re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+(\d{1,2}),?\s+(20\d{2})\b",re.I)
NUM_DATE_RE=re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b")
TIME_RE=re.compile(r"\b(\d{1,2}):(\d{2})\s*(AM|PM)\s*(EDT|EST|ET)\b",re.I)
MONTHS={m.lower()[:3]:i for i,m in enumerate(["January","February","March","April","May","June","July","August","September","October","November","December"],1)}
MONTHS["sep"]=9
# Require a grammatical announcement of upcoming results immediately before a date.
# A news publication timestamp or quarter-end date by itself is NEVER enough.
RELEASE_CONTEXT_RE=re.compile(
 r"\b(?:will|to|plans?\s+to|expects?\s+to)\s+(?:report|announce|release|publish|host|discuss)\b"
 r".{0,180}?\b(?:earnings|financial|results|quarter|conference\s+call|webcast)\b"
 r".{0,160}?\b(?:on|for)\s+(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+)?"
 r"(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
 r"\.?\s+\d{1,2},?\s+20\d{2}\b",re.I)

def host_allowed(url, suffixes):
 try:
  p=urllib.parse.urlsplit(url)
  if p.scheme!="https":return False
  h=(p.hostname or "").lower()
  return any(h==s or h.endswith("."+s) for s in suffixes)
 except ValueError:return False
def getfeed(url,suffixes):
 if not host_allowed(url,suffixes):raise ValueError("feed host not allowed")
 q=urllib.request.Request(url,headers={"User-Agent":AGENT,"Accept":"application/rss+xml,application/xml,text/xml,application/atom+xml"})
 with urllib.request.urlopen(q,timeout=12) as r:
  b=r.read(1_200_001)
 if len(b)>1_200_000:raise ValueError("feed too large")
 root=ET.fromstring(b)
 items=[]
 for x in root.iter():
  if x.tag.rsplit("}",1)[-1] not in ("item","entry"):continue
  fields={}
  for y in x:
   tag=y.tag.rsplit("}",1)[-1]
   if tag in ("title","description","summary","pubDate","published","updated","link","content"):
    val="".join(y.itertext()).strip()
    if tag=="link" and not val:val=y.attrib.get("href","").strip()
    fields[tag]=val[:25000]
  items.append(fields)
 return items[:30]
def article_date(item):
 stamp=item.get("pubDate") or item.get("published") or item.get("updated") or ""
 try:
  v=email.utils.parsedate_to_datetime(stamp)
  if v.tzinfo:return v.astimezone(JST).date().isoformat()
 except (TypeError,ValueError,OverflowError):pass
 try:return dt.datetime.fromisoformat(stamp.replace("Z","+00:00")).astimezone(JST).date().isoformat()
 except ValueError:return ""
def read_explicit_date(title):
 m=MONTH_RE.search(title)
 if m:
  mo=m.group(1).lower()[:3]
  if mo not in MONTHS:return None
  try:return dt.date(int(m.group(3)),MONTHS[mo],int(m.group(2)))
  except ValueError:return None
 m=NUM_DATE_RE.search(title)
 if m:
  try:return dt.date(int(m.group(3)),int(m.group(1)),int(m.group(2)))
  except ValueError:return None
 return None
def date_from_announcement_description(item):
 for field in ("description","summary","content"):
  raw=item.get(field,"")
  if not raw:continue
  plain=re.sub(r"\s+"," ",html.unescape(re.sub(r"<[^>]+>"," ",raw)))
  for match in RELEASE_CONTEXT_RE.finditer(plain):
   value=read_explicit_date(match.group(0))
   if value:return value
 return None

def earnings_event(company,symbol,item,url):
 title=html.unescape(re.sub(r"<[^>]+>"," ",item.get("title","")))
 if not (NEWS_RE.search(title) and FUTURE_RE.search(title)):
  return None
 market_date=read_explicit_date(title) or date_from_announcement_description(item)
 if not market_date:return None
 now=dt.datetime.now(JST).date()
 if not now-dt.timedelta(days=1)<=market_date<=now+dt.timedelta(days=425):return None
 m=TIME_RE.search(title)
 if m:
  hour,minute,meridian,zone=m.groups()
  h=int(hour)%12+(12 if meridian.upper()=="PM" else 0)
  # Explicit EST/EDT markers must match Eastern seasonal offset for that date.
  local=dt.datetime.combine(market_date,dt.time(h,int(minute)),tzinfo=EASTERN)
  actual=local.strftime("%Z")
  if zone.upper() in ("EST","EDT") and actual!=zone.upper():
   return None
  jst=local.astimezone(JST)
  when=jst.date().isoformat()
  time=jst.strftime("%H:%M")
  label="説明会等 "+time+" JST（元記事の時刻を変換）"
 else:
  when=market_date.isoformat()
  time=""
  label="米国現地の予定日（日本時間・発表時刻は未確認）"
 digest=hashlib.sha256((symbol+":"+market_date.isoformat()).encode()).hexdigest()[:12]
 return {"id":"large-ir-"+symbol.lower()+"-"+digest,"date":when,"time":time,
 "marketDate":market_date.isoformat(),"title":company+" 決算関連予定（公式IR告知）",
 "symbol":symbol,"region":"US","category":"earnings","importance":"high",
 "confidence":"confirmed","sourceName":company+"公式IR RSS",
 "sourceUrl":url,"detail":"公式RSSの見出しに明記された決算関連イベントの米国現地予定日。時刻未記載なら日本時間の発表時刻は未確認です。決算資料公開日と説明会の日付が違う場合があります。",
 "timeLabel":label,"automated":True}
def main():
 data=json.loads(DATA.read_text(encoding="utf-8"))
 ir=json.loads(NEWS.read_text(encoding="utf-8"))
 now=dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
 statuses=[]
 headlines=[]
 new_events=[]
 for company,symbol,feed,suffixes in FEEDS:
  try:
   items=getfeed(feed,suffixes)
   matched=0
   for item in items:
    title=re.sub(r"\s+"," ",html.unescape(re.sub(r"<[^>]+>"," ",item.get("title","")))).strip()
    if not (title and NEWS_RE.search(title)):continue
    link=item.get("link","").strip()
    if not host_allowed(link,suffixes):continue
    matched+=1
    headlines.append({"company":company,"symbol":symbol,"title":title[:180],
      "articlePublishedDate":article_date(item),"sourceName":company+"公式IR RSS",
      "sourceUrl":link,"kind":"ir-news-not-earnings-date"})
    candidate=earnings_event(company,symbol,item,link)
    if candidate:new_events.append(candidate)
   statuses.append({"name":company+" / "+urllib.parse.urlsplit(feed).path.rsplit("/",1)[-1],
     "status":"ok","matches":matched})
   print("Official RSS OK",company,matched)
  except Exception as e:
   statuses.append({"name":company+" / "+urllib.parse.urlsplit(feed).path.rsplit("/",1)[-1],
    "status":"unavailable","detail":str(e)[:120]})
   print("Official RSS unavailable, no bypass:",company,type(e).__name__,str(e)[:100])
 added=0
 for event in new_events:
  # A previously verified calendar event takes precedence over a headline.
  if any(x.get("category")=="earnings" and x.get("symbol")==event["symbol"]
    and (x.get("marketDate")==event["marketDate"] or x.get("date")==event["date"])
    for x in data["events"]):continue
  data["events"].append(event);added+=1
 if headlines:
  unique={x.get("sourceUrl"):x for x in headlines+ir.get("notices",[]) if x.get("sourceUrl")}
  ir["notices"]=sorted(unique.values(),key=lambda x:x.get("articlePublishedDate",""),reverse=True)[:55]
 ir["majorCompaniesSources"]=statuses
 ir["majorCompaniesCheckedAt"]=now
 NEWS.write_text(json.dumps(ir,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 status=data.setdefault("dataStatus",{})
 ok=sum(x["status"]=="ok" for x in statuses)
 status["majorEarnings"]=f"公式RSS {ok}/{len(FEEDS)}取得成功・新規決算日 {added}件"
 data["majorEarningsCheckedAt"]=now
 data["events"].sort(key=lambda e:(e.get("date",""),e.get("time",""),e.get("id","")))
 DATA.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(status["majorEarnings"])
if __name__=="__main__":main()
