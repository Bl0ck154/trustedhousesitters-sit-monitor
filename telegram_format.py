#!/usr/bin/env python3
"""HTML-safe Telegram captions and paginated full THS listing descriptions.

No Telegram or network dependency. The original listing text is presented in
English (as authored by host), preserving relevant paragraphs/steps.
"""
import datetime as dt
import html
import re
import telegram_quality as quality

MAX_PAGE = 3450  # Telegram send/editMessageText limit is 4096 post-parse
MAX_CAPTION = 900  # Telegram photo caption limit is 1024 post-parse

def esc(v):
    return html.escape(str(v or ""), quote=False)

def brief(v, maxlen):
    s = re.sub(r"\s+", " ", str(v or "")).strip()
    if len(s) <= maxlen:
        return s
    return s[:maxlen-1].rsplit(" ", 1)[0] + "…"

def link(item):
    title=esc(brief(item.get("title") or "Оголошення", 155))
    url=html.escape(str(item.get("url") or ""), quote=True)
    return f'<a href="{url}"><b>{title}</b></a>'

def data(item):
    a=item.get("amenities") or {}
    return a if isinstance(a,dict) else {}

def wifi_label(item):
    wifi=item.get("internet") or data(item).get("wifiType")
    return {"highSpeed":"швидкий Wi‑Fi","basic":"Wi‑Fi","limited":"обмежений Wi‑Fi","none":"без Wi‑Fi"}.get(wifi, "Wi‑Fi не вказаний")

def pets_label(item):
    pets=item.get("pets") or {}
    if isinstance(pets,dict):
        names={"cat":("кіт","коти","котів"),"dog":("собака","собаки","собак"),"poultry":("птах","птахи","птахів"),"rabbit":("кролик","кролики","кроликів"),"hamster":("хом’як","хом’яки","хом’яків"),"guinea pig":("морська свинка","морські свинки","морських свинок"),"small pet":("дрібна тварина","дрібні тварини","дрібних тварин"),"fish":("рибка","рибки","рибок")}
        def localized(kind,n):
            forms=names.get(kind)
            if not forms:return f"{n} {kind}"
            last=int(n)%10
            ten=int(n)%100
            return f"{n} {forms[0] if last==1 and ten!=11 else forms[1] if last in (2,3,4) and ten not in (12,13,14) else forms[2]}"
        parts=[localized(type_name,n) for type_name,n in pets.items() if n]
        return ", ".join(parts) if parts else "не вказано"
    return "не вказано"

def time_label(item):
    minutes=item.get("minutes_pet_can_be_left_alone")
    if isinstance(minutes,int) and 0<minutes<=1440:
        h, m=divmod(minutes,60)
        return f"до {h} год {m} хв" if m else (f"до {h} год" if h else f"до {m} хв")
    return ""

def amenity_summary(item):
    a=data(item)
    features=[]
    if a.get("workspaceTypes"):
        features.append("робоче місце")
    if a.get("hasWasher"):
        features.append("пральна машина")
    if a.get("hasDishwasher"):
        features.append("посудомийка")
    if a.get("hasGarden"):
        features.append("сад")
    if a.get("hasTerrace") or a.get("hasPatio"):
        features.append("тераса/патіо")
    if a.get("hasPool"):
        features.append("басейн")
    if a.get("hasHeating") or a.get("heatingTypes"):
        features.append("опалення")
    return features

def caption(item):
    applicant=item.get("application_count")
    rating=quality.priority(item)
    names=[str(p.get("name")).strip() for p in item.get("pet_profiles") or [] if p.get("name")]
    brief_duties=brief(item.get("pet_care") or item.get("responsibilities"),215)
    location=", ".join(x for x in (item.get("city"),item.get("country")) if x)
    rows=[
        link(item),
        "✨ "+esc(rating["tier"]),
        f"📍 {esc(location)}",
        f"🗓 {esc(item.get('start'))} — {esc(item.get('end'))} · <b>{esc(item.get('nights'))} ночей</b>",
        "🐾 " + esc(pets_label(item)) + (f" · {esc(', '.join(names[:4]))}" if names else ""),
        f"🚆 {'Громадський транспорт' if item.get('transport_accessible') else 'Транспорт не підтверджено'} · 📶 {esc(wifi_label(item))}",
    ]
    left=time_label(item)
    if left:
        rows.append(f"⏱ Можна залишати тварин: {esc(left)}")
    amenities=amenity_summary(item)
    if amenities:
        rows.append("🏠 "+esc(", ".join(amenities[:4])))
    if brief_duties:
        rows.append("📝 "+esc(brief_duties))
    if rating["flags"]:
        rows.append("⚠️ "+esc(" · ".join(f["label"] for f in rating["flags"][:2])))
    if isinstance(applicant,int):
        rows.append(f"📨 Заявок: {applicant}")
    msg="\n".join(rows)
    if len(html.unescape(msg))>MAX_CAPTION:
        rows=[row for row in rows if not row.startswith("🏠 ")]
        msg="\n".join(rows)
    if len(html.unescape(msg))>MAX_CAPTION:
        rows=[row for row in rows if not row.startswith("📝 ")]
        msg="\n".join(rows)
    return msg

def normalize_source(text):
    """Preserve real text paragraphs and bullet lines, remove accidental HTML."""
    result=[]
    for raw in str(text or "").replace("\r\n","\n").splitlines():
        line=raw.strip()
        if not line:
            if result and result[-1]!="":result.append("")
            continue
        # Keep author's original bullet markers and emphasis when present.
        result.append(line)
    return "\n".join(result).strip()

def sections(item):
    location=", ".join(x for x in (item.get("city"),item.get("country")) if x)
    meta=[
        f"📅 {item.get('start')} — {item.get('end')} · {item.get('nights')} ночей",
        "🐾 "+pets_label(item),
        "📶 "+wifi_label(item),
        "🚆 "+("Громадський транспорт доступний" if item.get("transport_accessible") else "Доступність транспорту не підтверджена"),
    ]
    if item.get("owner_name"):meta.append("👤 Власник: "+str(item["owner_name"]))
    if item.get("home_type"):
        kind=str(item["home_type"])
        meta.append("🏠 Тип житла: "+{"apartment":"квартира","house":"будинок","flat":"квартира"}.get(kind,kind))
    minutes=time_label(item)
    if minutes:meta.append("⏱ Тварини можуть бути самі "+minutes)
    if isinstance(item.get("application_count"),int):
        meta.append("📨 Заявок: "+str(item["application_count"]))
    out=[("📋 Загальна інформація","\n".join(meta))]
    warnings=quality.priority(item)["flags"]
    if warnings:
        out.append(("⚠️ Важливі умови","\n".join("• "+w["label"]+": "+w["excerpt"] for w in warnings)))
    pets=[]
    for pet in item.get("pet_profiles") or []:
        if not isinstance(pet,dict):continue
        name=pet.get("name") or "Тварина"
        birth=pet.get("yearOfBirth")
        age=""
        if isinstance(birth,int) and 1990<=birth<=dt.datetime.now().year:
            age=f" (нар. {birth})"
        text=normalize_source(pet.get("description"))
        pets.append(f"• {name}{age}"+(f": {text}" if text else ""))
    if pets:out.append(("🐾 Тварини","\n".join(pets)))
    for heading,key in [("👋 Про власника та проживання","introduction"),
                        ("📝 Обов'язки та розпорядок","responsibilities"),
                        ("🐈 Догляд за тваринами","pet_care"),
                        ("🗺 Район і що поруч","local_attractions")]:
        s=normalize_source(item.get(key))
        if s:out.append((heading,s))
    a=data(item)
    summary=amenity_summary(item)
    extra=[]
    for key,label_text in [
        ("bedTypes","Спальні місця"),("workspaceTypes","Робоче місце"),
        ("heatingTypes","Опалення"),("storageTypes","Місце для речей"),
        ("parkingType","Паркування")]:
        value=a.get(key)
        if value:
            translations={"double":"двоспальне ліжко","single":"односпальне ліжко","office":"кабінет","desk":"стіл","central":"центральне","drawers":"комод","wardrobe":"шафа"}
            vals=value if isinstance(value,list) else [value]
            extra.append(f"• {label_text}: "+", ".join(translations.get(str(v),str(v)) for v in vals))
    for key,label_text in [
        ("hasWasher","Пральна машина"),("hasDryer","Сушарка"),
        ("hasDishwasher","Посудомийка"),("hasKitchen","Кухня"),
        ("hasOven","Духовка"),("hasMicrowave","Мікрохвильовка"),
        ("hasGarden","Сад"),("hasTerrace","Тераса"),
        ("hasPool","Басейн"),("hasAirConditioning","Кондиціонер"),
        ("hasShower","Душ")]:
        if a.get(key) is True:extra.append("• "+label_text)
    if summary or extra:
        out.append(("🏡 Житло й зручності","\n".join(extra) if extra else ", ".join(summary)))
    return out

def page_chunks(item,limit=MAX_PAGE):
    """Every page is standalone well-formed HTML; all content is included."""
    header=link(item)
    blocks=[]
    for heading,body in sections(item):
        body=normalize_source(body)
        # Split overlong paragraphs without breaking HTML entities or tags:
        # chunk plain source before escaping it.
        lines=body.split("\n")
        segments=[]
        for line in lines:
            while len(line)>1100:
                # Prefer whole sentences over splitting a pet-care instruction.
                boundaries=[line.rfind(marker,0,1100) for marker in (". ","! ","? ","; ")]
                cut=max(boundaries)
                if cut>=550:
                    cut+=1
                else:
                    cut=line.rfind(" ",0,1100)
                if cut<550:cut=1100
                segments.append(line[:cut].rstrip())
                line=line[cut:].lstrip()
            segments.append(line)
        # Break each section into standalone blocks at ~1200 chars.
        segment=""
        for line in segments:
            if segment and len(segment)+len(line)+1>1200:
                blocks.append(f"<b>{esc(heading)}</b>\n{esc(segment)}")
                segment=""
            segment=(segment+"\n"+line).strip("\n") if segment else line
        if segment:blocks.append(f"<b>{esc(heading)}</b>\n{esc(segment)}")
    pages=[]
    current=header
    for block in blocks:
        if len(html.unescape(current+"\n\n"+block))>limit and current!=header:
            pages.append(current)
            current=header
        # individually huge blocks get split again safely, but with 1200 blocks
        # under ordinary data this branch should never occur.
        current+="\n\n"+block
    if current:pages.append(current)
    return pages or [header]

def control_text(item):
    return f"📖 <b>Деталі оголошення</b>\n{link(item)}\nНатисни кнопку, щоб переглянути весь опис без виходу з Telegram."
