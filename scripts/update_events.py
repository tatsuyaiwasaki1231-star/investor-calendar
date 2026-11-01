#!/usr/bin/env python3
"""Updates the economic indicators in data/events.json from the US BLS calendar.
Earnings and Bank of Japan/FOMC events are static unless manually refreshed.
This script deliberately preserves existing events when upstream fetch fails.
"""
import datetime as dt
import json
import re
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data/events.json"
NY=ZoneInfo("America/New_York")
JST=ZoneInfo("Asia/Tokyo")
URL="https://www.bls.gov/schedule/news_release/bls.ics"
LOOKUP={
    "employment situation":("米雇用統計","high"),
    "consumer price index":("米CPI","high"),
    "producer price index":("米PPI","medium"),
    "job openings and labor turnover survey":("米JOLTS求人件数","medium"),
    "employment cost index":("米雇用コスト指数","medium")
}
def events_from_ics(raw):
    lines=[]
    for line in raw.replace("\r\n","\n").split("\n"):
        if line.startswith((" ","\t")) and lines:lines[-1]+=line[1:]
        else:lines.append(line)
    chunks=[];current=None
    for line in lines:
        if line=="BEGIN:VEVENT":current={}
        elif line=="END:VEVENT":
            if current is not None:chunks.append(current)
            current=None
        elif current is not None and ":" in line:
            k,v=line.split(":",1); current[k]=v
    output=[]
    for chunk in chunks:
        summary=next((v for k,v in chunk.items() if k.startswith("SUMMARY")),"")
        picked=next(((name,priority) for phrase,(name,priority) in LOOKUP.items() if phrase in summary.lower()),None)
        if not picked:continue
        pair=next(((k,v) for k,v in chunk.items() if k.startswith("DTSTART")),None)
        if not pair:continue
        key,value=pair
        try:
            if re.fullmatch(r"\d{8}",value):
                date=dt.datetime.strptime(value,"%Y%m%d").date()
                when=date.isoformat(); time="";label="米現地日付／時刻不明"
            else:
                stamp=dt.datetime.strptime(value.rstrip("Z")[:15],"%Y%m%dT%H%M%S")
                if value.endswith("Z"):stamp=stamp.replace(tzinfo=dt.timezone.utc)
                elif "America/New_York" in key or "US/Eastern" in key:stamp=stamp.replace(tzinfo=NY)
                else:continue
                date=stamp.astimezone(NY).date()
                local=stamp.astimezone(JST)
                when=local.date().isoformat();time=local.strftime("%H:%M");label="発表 "+time+" JST"
        except ValueError:continue
        if not dt.date.today()-dt.timedelta(days=10)<=date<=dt.date.today()+dt.timedelta(days=465):continue
        name,importance=picked
        output.append(dict(id="bls-"+re.sub(r"[^a-z0-9]+","-",name.lower())+"-"+date.isoformat(),date=when,time=time,marketDate=date.isoformat(),title=name,symbol="",region="US",category="macro",importance=importance,confidence="confirmed",sourceName="米BLS公式ICS",sourceUrl=URL,detail=summary+"。米労働統計局の発表予定から自動取得。",timeLabel=label,automated=True))
    return output

def main():
    data=json.loads(DATA.read_text(encoding="utf-8"))
    request=urllib.request.Request(URL,headers={"User-Agent":"Mozilla/5.0 (compatible; investor-calendar/1.0)"})
    try:
        with urllib.request.urlopen(request,timeout=30) as response:
            fetched=events_from_ics(response.read().decode("utf-8-sig",errors="replace"))
        if not fetched:raise RuntimeError("BLS calendar gave zero matching future events")
        old=[e for e in data["events"] if not str(e.get("id","")).startswith("bls-")]
        old.extend(fetched)
        data["events"]=sorted(old,key=lambda x:(x.get("date",""),x.get("time",""),x.get("id","")))
        data.setdefault("dataStatus",{})["bls"]="ok ("+str(len(fetched))+")"
        print("BLS updated",len(fetched))
    except Exception as exc:
        data.setdefault("dataStatus",{})["bls"]="取得失敗・前回データを維持"
        print("BLS refresh failed; retaining events:",repr(exc))
    data["updatedAt"]=dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
    DATA.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
if __name__=="__main__":main()
