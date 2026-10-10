"""Personal house-sit itinerary and adaptive preferences (pure logic).

Dates are half-open [start, end); end is checkout/departure day.
A confirmed stay requires explicit owner action and never comes from
the site's public "Confirmed" listing status.
"""
import datetime as dt
import os
from pathlib import Path
from zoneinfo import ZoneInfo

SMALL={"small pet","rabbit","hamster","guinea pig","guinea-pig","rodent","rat","mouse","gerbil","chinchilla","fish"}
HARD={"horse","farm animal","livestock","reptile"}
HOME_COUNTRIES={
    "Germany":{"Austria","France","Netherlands","Belgium","Poland","Denmark","Czech Republic","Switzerland"},
    "Austria":{"Germany","Switzerland","Italy","Slovenia","Czech Republic","Hungary"},
    "France":{"Germany","Switzerland","Belgium","Italy","Spain","Luxembourg"},
    "Spain":{"France","Portugal"},
    "Portugal":{"Spain"},
}
DEFAULT_START=None

def today():
    return dt.datetime.now(ZoneInfo("Europe/Vilnius")).date()

def trip_start():
    configured=os.getenv("THS_EARLIEST_START")
    if not configured:
        private=Path(__file__).resolve().parent/"data"/"config.env"
        if private.is_file():
            for line in private.read_text(encoding="utf-8").splitlines():
                if line.startswith("THS_EARLIEST_START="):
                    configured=line.split("=",1)[1].strip()
                    break
    return dt.date.fromisoformat(configured) if configured else today()

def journey_window(confirmed=(),today_date=None,start=None,horizon_days=95):
    start=start or trip_start()
    now=today_date or today()
    end=start+dt.timedelta(days=horizon_days)
    cursor=start
    gaps=[]
    for stay in sorted(confirmed,key=lambda x:x["start"]):
        a,b=dt.date.fromisoformat(str(stay["start"])),dt.date.fromisoformat(str(stay["end"]))
        if b<=cursor or a>=end:continue
        if a>cursor:gaps.append((cursor,min(a,end)))
        cursor=max(cursor,b)
        if cursor>=end:break
    if cursor<end:gaps.append((cursor,end))
    # Gaps shorter than our normal minimum 7-night sit need a bridge,
    # not a misleading incompatible house-sit recommendation.
    future=[(max(a,now),b) for a,b in gaps if b>now]
    actual=[(a,b) for a,b in future if a<b]
    substantial=[(a,b) for a,b in actual if (b-a).days>=7]
    focus=substantial[0] if substantial else (actual[0] if actual else None)
    return {"start":start,"end":end,"gaps":actual,"focus":focus,
            "bridge_gaps":[(a,b) for a,b in actual if (b-a).days<7]}

def search_window(confirmed=(),today_date=None,start=None):
    now=today_date or today()
    trip=journey_window(confirmed,now,start)
    focus=trip["focus"]
    earliest=max(now,focus[0]) if focus else now
    if not confirmed:
        # Before the first booking, prioritize the immediate housing deadline.
        # Avoid filling the catalog with distant stays from six weeks away.
        latest=max(earliest+dt.timedelta(days=7),now+dt.timedelta(days=30))
    else:
        # After a booking, move the search window to the next uncovered period.
        latest=earliest+dt.timedelta(days=30)
    return earliest,min(trip["end"],latest)

def pet_tier(item):
    pets=item.get("pets") or {}
    counts={str(k).lower():int(v or 0) for k,v in pets.items() if int(v or 0)>0}
    if not counts:return "C"
    if any(k in HARD for k in counts):return "C"
    dogs=counts.get("dog",0)
    if dogs>2:return "C"
    if dogs:
        return "B" if not any(k not in SMALL|{"cat","dog"} for k in counts) else "C"
    if all(k in SMALL|{"cat"} for k in counts):return "A"
    return "C"

def possible(item):
    if item.get("status")!="open" or pet_tier(item)=="C":
        return False
    if item.get("transit_warning"):return False
    if item.get("internet") in ("none","noWifi"):return False
    return True

def overlaps(stay_a,stay_b):
    a1=dt.date.fromisoformat(str(stay_a["start"]))
    b1=dt.date.fromisoformat(str(stay_a["end"]))
    a2=dt.date.fromisoformat(str(stay_b["start"]))
    b2=dt.date.fromisoformat(str(stay_b["end"]))
    return a1<b2 and a2<b1

def candidate_fit(item,confirmed=(),today_date=None,start=None):
    """No overlap with confirmed nights, and cover some worthwhile future gap."""
    if not possible(item):return False
    if any(overlaps(item,s) for s in confirmed):return False
    trip=journey_window(confirmed,today_date,start)
    try:
        a=dt.date.fromisoformat(str(item["start"]))
        b=dt.date.fromisoformat(str(item["end"]))
    except (KeyError,ValueError,TypeError):
        return False
    focus=trip["focus"]
    if not focus:return False
    # Do not notify a sit that cannot bridge at least 7 nights of its
    # relevant uncovered period. Other gaps are visible in /plan.
    for x,y in trip["gaps"]:
        if (y-x).days<7:continue
        overlap=max(0,(min(b,y)-max(a,x)).days)
        if overlap>=7:return True
    return False

def urgent(confirmed=(),today_date=None,start=None):
    now=today_date or today()
    f=journey_window(confirmed,now,start)["focus"]
    return bool(f and (f[0]-now).days<=9)

def priority(item,confirmed=(),today_date=None,start=None):
    kind=pet_tier(item)
    score={"A":100,"B":55,"C":0}[kind]
    if kind=="A" and (item.get("pets") or {}).get("cat"):
        score+=12  # Cats are preferable to equally manageable other pets.
    focus=journey_window(confirmed,today_date,start)["focus"]
    if focus:
        try:
            offset=abs((dt.date.fromisoformat(str(item["start"]))-focus[0]).days)
            score+=max(0,30-offset*3)
        except (KeyError,ValueError,TypeError):
            pass
    if item.get("transport_accessible"):score+=12
    if item.get("internet")=="highSpeed":score+=10
    elif item.get("internet") in ("basic",):score+=6
    minutes=item.get("minutes_pet_can_be_left_alone")
    if isinstance(minutes,int) and minutes>=360:score+=8
    if item.get("transit_warning"):score-=50
    if item.get("country") in {"Spain","Portugal","France","Germany","Austria"}:score+=4
    if confirmed:
        last=sorted(confirmed,key=lambda x:x["end"])[-1]
        target=str(last.get("country") or "")
        country=str(item.get("country") or "")
        if country==target:score+=12
        elif country in HOME_COUNTRIES.get(target,set()):score+=5
    desc=" ".join(str(item.get(k) or "") for k in ("responsibilities","pet_care","introduction")).lower()
    if any(s in desc for s in ("must have a car","car required","own car essential","no public transport")):
        score-=90
    if any(s in desc for s in ("medication","insulin","injections","reactive dog","pulls hard","giant dog")):
        score-=24
    if kind=="B" and int((item.get("pets") or {}).get("dog") or 0)==2:score-=10
    return score

def should_alert(item,confirmed=(),today_date=None,start=None):
    if not candidate_fit(item,confirmed,today_date,start):return False
    tier=pet_tier(item)
    return tier=="A" or (tier=="B" and urgent(confirmed,today_date,start))
