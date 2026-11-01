#!/usr/bin/env python3
"""Update selected US economic release dates using the public, documented FRED API.

Requires optional FRED_API_KEY stored in GitHub Actions Secrets.
Does not scrape blocked pages, bypass access controls, or guess release times.
Preserves the calendar when API access is unavailable.
"""
import datetime as dt
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

DATA = Path(__file__).resolve().parents[1] / "data/events.json"
JST = ZoneInfo("Asia/Tokyo")
RELEASES = {
    50: ("米雇用統計", "high", "雇用統計"),
    10: ("米CPI", "high", "米CPI"),
    46: ("米PPI", "medium", "米PPI"),
    9: ("米小売売上高", "medium", "小売売上高"),
    53: ("米GDP", "high", "米GDP"),
}
API_BASE = "https://api.stlouisfed.org/fred/release/dates"

def get_release_dates(release_id, key):
    params = urllib.parse.urlencode({
        "release_id": release_id,
        "api_key": key,
        "file_type": "json",
        "include_release_dates_with_no_data": "true",
        "sort_order": "desc",
        "limit": "120",
    })
    url = API_BASE + "?" + params
    request = urllib.request.Request(
        url, headers={"User-Agent": "InvestorCalendar/1.0 (personal non-commercial use)", "Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
    if "release_dates" not in payload:
        raise ValueError("FRED response missing release_dates")
    today = dt.datetime.now(JST).date()
    end = today + dt.timedelta(days=425)
    result = set()
    for item in payload["release_dates"]:
        date_str = item.get("date", "")
        try:
            date = dt.date.fromisoformat(date_str)
        except ValueError:
            continue
        if today - dt.timedelta(days=1) <= date <= end:
            result.add(date_str)
    return sorted(result)

def main():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    data.setdefault("dataStatus", {})
    data["dataStatus"]["bls"] = "直接取得停止（アクセス制限を尊重）"
    data["dataStatus"]["fmp"] = "未設定（米国企業の決算予定APIは未接続）"
    data["dataStatus"]["fred"] = "未設定（無料APIキーが必要）"
    data["syncCheckedAt"] = dt.datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
    data["warnings"] = []
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        data["warnings"].append("FRED_API_KEY未設定。登録済み日程を表示しています。")
        print("FRED_API_KEY missing; calendar unchanged")
    else:
        ok = 0
        added = 0
        for release_id, (name, importance, match) in RELEASES.items():
            try:
                dates = get_release_dates(release_id, key)
                if not dates:
                    print(f"No upcoming FRED releases for {name}; keeping current calendar")
                    continue
                ok += 1
                # Remove ONLY entries previously created by this API, for this release.
                data["events"] = [e for e in data["events"]
                                  if not str(e.get("id", "")).startswith(f"fred-{release_id}-")]
                for date in dates:
                    # Avoid duplicating a manually verified same-day schedule.
                    same_day = any(e.get("date") == date and e.get("category") == "macro" and
                                   match in str(e.get("title", "")) and
                                   not ("ADP" in str(e.get("title", "")) and release_id == 50)
                                   for e in data["events"])
                    if same_day:
                        continue
                    data["events"].append({
                        "id": f"fred-{release_id}-{date}",
                        "date": date,
                        "time": "",
                        "marketDate": date,
                        "title": name + "（発表予定日）",
                        "symbol": "",
                        "region": "US",
                        "category": "macro",
                        "importance": importance,
                        "confidence": "api",
                        "sourceName": "セントルイス連銀 FRED 発表予定日API",
                        "sourceUrl": f"https://fred.stlouisfed.org/releases/calendar?rid={release_id}",
                        "detail": "FREDに掲載された米国現地の発表予定日。日本時間の発表時刻は未確認。発表日程は変更される場合があります。",
                        "timeLabel": "米国現地日付・日本時間は要確認",
                        "automated": True,
                    })
                    added += 1
            except Exception as exc:
                print("FRED fetch failed:", release_id, repr(exc))
                data["warnings"].append(f"{name}: FRED取得失敗。前回登録分を保持。")
        data["dataStatus"]["fred"] = f"取得成功 {ok}/{len(RELEASES)}系列・新規{added}件" if ok else "取得失敗・前回登録分を保持"
        if ok:
            data["lastOfficialSyncAt"] = data["syncCheckedAt"]
            data["updatedAt"] = data["syncCheckedAt"]
    data["events"].sort(key=lambda e: (e.get("date", ""), e.get("time", ""), e.get("id", "")))
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
