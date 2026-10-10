"""Private, readable housing timeline and alternatives for Telegram."""
import datetime as dt
import html
import json
import pathlib

import housing_plan as plan
import housing_state as state

HOME=pathlib.Path(__file__).resolve().parent
DATA=HOME/"data"

def esc(v):
    return html.escape(str(v or ""),quote=False)

def _link(item):
    name=esc(item.get("title") or item.get("assignment_id"))
    url=str(item.get("url") or "")
    if url.startswith("https://www.trustedhousesitters.com/house-and-pet-sitting-assignments/"):
        return f'<a href="{html.escape(url,quote=True)}">{name}</a>'
    return name

def candidates(confirmed=(),today_date=None,applied_ids=()):
    """Latest full-search data, no extra THS requests for /options or daily."""
    p=DATA/"latest.json"
    if not p.is_file():return []
    try: payload=json.loads(p.read_text())
    except (ValueError,OSError):return []
    rows=[]
    for x in payload.get("results") or []:
        try:
            if plan.candidate_fit(x,confirmed,today_date):
                rows.append(x)
        except (KeyError,ValueError,TypeError):continue
    used=set(str(x) for x in applied_ids)
    return sorted(rows,key=lambda i:(str(i.get("assignment_id")) in used,
                                     -plan.priority(i,confirmed,today_date)))

def options_text(conn,today_date=None):
    stays=state.confirmed(conn)
    used={a["assignment_id"] for a in state.applications(conn)
          if a["stage"] in ("applied","talking","confirmed")}
    rows=candidates(stays,today_date,used)
    a=[x for x in rows if plan.pet_tier(x)=="A"]
    b=[x for x in rows if plan.pet_tier(x)=="B"]
    parts=["🔎 <b>Варіанти житла</b>",
           f"🐈 Коти / дрібні тварини: <b>{len(a)}</b> · 🐕 Собаки (резерв): <b>{len(b)}</b>"]
    for label,items in [("Пріоритетні",a),("Запасні",b)]:
        if not items:continue
        parts.append("<b>"+label+"</b>")
        for item in items[:5]:
            pets=", ".join(f"{n}×{k}" for k,n in (item.get("pets") or {}).items() if n)
            note=" · потрібна перевірка деталей" if not item.get("verified_by_detail") else ""
            parts.append("• "+_link(item)+" — "+esc(item.get("city"))+
                         " · "+esc(item.get("start"))+"–"+esc(item.get("end"))+
                         " · "+esc(pets)+esc(note)+" · ID: <code>"+esc(item.get("assignment_id"))+"</code>")
    if not rows:parts.append("Зараз у збереженій повній вибірці немає придатних варіантів.")
    parts.append("<i>Запасні варіанти збираються завчасно. Наявність місця перевіряється перед сповіщенням.</i>")
    return "\n".join(parts)[:3950]

def plan_text(conn,today_date=None):
    now=today_date or plan.today()
    stays=state.confirmed(conn)
    journey=plan.journey_window(stays,now)
    focus=journey["focus"]
    parts=["🏠 <b>План житла</b>",
           "Початок пошуку: <b>"+esc(journey["start"].isoformat())+"</b> · горизонт 95 днів"]
    if not stays:parts.append("🔴 <b>Підтверджених проживань ще немає.</b>")
    else:
        parts.append("✅ <b>Підтверджено вручну:</b>")
        for x in stays:
            parts.append("• "+esc(x["start"])+"–"+esc(x["end"])+" · "+
                         esc(x.get("city"))+", "+esc(x.get("country")))
    if focus:
        parts.append("🎯 Наступне вікно: <b>"+esc(focus[0].isoformat())+
                     " — "+esc(focus[1].isoformat())+"</b>")
        days=max(0,(focus[0]-now).days)
        parts.append("⏳ До початку: <b>"+str(days)+" днів</b>")
    for a,b in journey["bridge_gaps"][:3]:
        parts.append("⚠️ Прогалина <b>"+str((b-a).days)+" ночей</b> ("+
                     esc(a.isoformat())+"–"+esc(b.isoformat())+
                     ") — потрібен короткий місток або окреме житло.")
    parts.append("🐕 Резерв із собаками: "+("активні сповіщення" if plan.urgent(stays,now) else "окремий список /options"))
    parts.append("<i>Сайт може показувати Confirmed для іншого ситтера. Лише ти позначаєш власне підтвердження через /confirm або кнопку.</i>")
    return "\n".join(parts)[:3950]

def applications_text(conn):
    apps=state.applications(conn)
    if not apps:return "📋 <b>Заявки</b>\nПоки немає відмічених заявок."
    parts=["📋 <b>Мої заявки</b> · статуси позначаються вручну"]
    for app in apps[:20]:
        item=state.snapshot(conn,app["assignment_id"],DATA/"listings") or {}
        site=conn.execute("SELECT status FROM watch WHERE assignment_id=?",
                          (app["assignment_id"],)).fetchone()
        parts.append("• "+_link(item or {"assignment_id":app["assignment_id"]})+
                     "\n  "+esc(item.get("city") or "")+" · "+
                     esc(item.get("start") or "?")+"–"+esc(item.get("end") or "?")+
                     "\n  "+state.LABELS.get(app["stage"],esc(app["stage"]))+" · ID: <code>"+esc(app["assignment_id"])+"</code>"+
                     " · стан оголошення: "+esc(site[0] if site else "невідомий"))
    parts.append("\nКоманди: /talking ID · /confirm ID · /reject ID · /applied ID · /withdraw ID")
    return "\n".join(parts)[:3950]

def daily_text(conn,today_date=None):
    now=today_date or plan.today()
    stays=state.confirmed(conn)
    apps=state.applications(conn)
    stage_counts={}
    for a in apps:stage_counts[a["stage"]]=stage_counts.get(a["stage"],0)+1
    used={a["assignment_id"] for a in apps if a["stage"] in ("applied","talking","confirmed")}
    top=candidates(stays,now,used)
    first=plan.journey_window(stays,now)["focus"]
    lines=["☀️ <b>Житло · "+now.isoformat()+"</b>"]
    if first:
        days=max(0,(first[0]-now).days)
        lines.append("⏳ Наступна незакрита дата: <b>"+first[0].isoformat()+
                     "</b> · "+str(days)+" днів")
    lines.append("📨 Подано: "+str(stage_counts.get("applied",0))+
                 " · 💬 Відповіли: "+str(stage_counts.get("talking",0))+
                 " · ✅ Підтверджено: "+str(len(stays))+
                 " · ❌ Відмовили: "+str(stage_counts.get("rejected",0)))
    a=[x for x in top if plan.pet_tier(x)=="A"]
    b=[x for x in top if plan.pet_tier(x)=="B"]
    lines.append(f"🐈 Основні: <b>{len(a)}</b> · 🐕 Резерв: <b>{len(b)}</b>")
    fresh=[x for x in top if str(x.get("assignment_id")) not in used]
    featured=(fresh or top)[:3]
    for item in featured:
        label="🐕 резерв · " if plan.pet_tier(item)=="B" else ""
        lines.append("• "+label+_link(item)+" — "+esc(item.get("city"))+
                     ", "+esc(item.get("start")))
    if plan.urgent(stays,now) and not stays:
        lines.append("⚠️ Менше 10 днів до потрібного житла: розглядай резерв із собаками та тимчасову кімнату.")
    lines.append("Деталі: /plan · /options · /applications")
    return "\n".join(lines)[:3950]
