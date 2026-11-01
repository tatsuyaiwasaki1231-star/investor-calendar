#!/usr/bin/env python3
"""Read public company RSS headlines, never infer an earnings date from publication date."""
import datetime as dt
import email.utils
import json
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

OUTPUT = Path(__file__).resolve().parents[1] / "data" / "ir_notices.json"
SOURCES = [
 ("NVIDIA", "NVDA", "NVIDIA公式IRイベントRSS", "https://investor.nvidia.com/rss/event.aspx"),
 ("NVIDIA", "NVDA", "NVIDIA公式プレスリリースRSS", "https://nvidianews.nvidia.com/cats/press_release.xml")
]
KEYWORDS = ("earnings", "financial results", "quarter", "conference call", "financial performance")
ALLOWED = {"investor.nvidia.com", "nvidianews.nvidia.com"}
JST = ZoneInfo("Asia/Tokyo")

def get_text(node, field):
 for child in node:
  if child.tag.split("}")[-1].lower() == field.lower():
   return "".join(child.itertext()).strip()
 return ""

def fetch(source):
 company, symbol, name, url = source
 if urlparse(url).hostname not in ALLOWED: raise ValueError("feed not allowlisted")
 request=urllib.request.Request(url, headers={"User-Agent":"InvestorCalendar/1.0 (public IR RSS reader)","Accept":"application/xml,application/rss+xml,text/xml"})
 with urllib.request.urlopen(request,timeout=15) as response:
  data=response.read(1_000_001)
 if len(data)>1_000_000: raise ValueError("feed too large")
 root=ET.fromstring(data)
 notices=[]
 for node in root.iter():
  if node.tag.split("}")[-1] not in ("item","entry"):continue
  title=get_text(node,"title")
  if not any(x in title.lower() for x in KEYWORDS):continue
  link=get_text(node,"link")
  if not link:
   tag=next((x for x in node if x.tag.split("}")[-1]=="link"),None)
   if tag is not None:link=tag.attrib.get("href","")
  if not link.startswith("https://"):continue
  stamp=get_text(node,"pubDate") or get_text(node,"published") or get_text(node,"updated")
  published=""
  try:
   when=email.utils.parsedate_to_datetime(stamp)
   if when.tzinfo:published=when.astimezone(JST).date().isoformat()
  except (TypeError,ValueError,OverflowError):pass
  if not published and stamp:
   try:published=dt.datetime.fromisoformat(stamp.replace("Z","+00:00")).astimezone(JST).date().isoformat()
   except ValueError:pass
  notices.append({"company":company,"symbol":symbol,"title":title[:180],"articlePublishedDate":published,"sourceName":name,"sourceUrl":link,"kind":"ir-news-not-earnings-date"})
 return notices

def main():
 previous={}
 if OUTPUT.exists():
  try:previous=json.loads(OUTPUT.read_text(encoding="utf-8"))
  except (ValueError,OSError):pass
 statuses=[]
 items=[]
 for source in SOURCES:
  try:
   incoming=fetch(source);items.extend(incoming)
   statuses.append({"name":source[2],"status":"ok","matches":len(incoming)})
   print("RSS OK",source[2],len(incoming),"related headlines")
  except Exception as exc:
   statuses.append({"name":source[2],"status":"error","message":str(exc)[:140]})
   print("RSS not accessible; no bypass:",source[2],str(exc)[:110])
 now=dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
 output={"checkedAt":now,"status":"ok" if any(x["status"]=="ok" for x in statuses) else "unavailable","sources":statuses,"notices":previous.get("notices",[])}
 if items:
  output["notices"]=sorted({x["sourceUrl"]:x for x in items}.values(),key=lambda x:x["articlePublishedDate"],reverse=True)[:15]
  output["lastSuccessAt"]=now
 elif previous.get("lastSuccessAt"):output["lastSuccessAt"]=previous["lastSuccessAt"]
 OUTPUT.parent.mkdir(parents=True,exist_ok=True)
 OUTPUT.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
if __name__=="__main__":main()
