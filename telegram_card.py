"""Single-message interactive Telegram photo card for one TrustedHousesitters sit.

Telegram media groups have no inline keyboards. This module uses one photo,
up to 3 gallery images via editMessageMedia, and 1024-char caption pages.
"""
import html
import json
import re
from urllib.parse import quote
import telegram_format as oldfmt
import telegram_quality as quality

CAP_LIMIT=890
def e(v):return html.escape(str(v or ""),quote=False)

def link(item):
    name=oldfmt.brief(item.get("title") or "Оголошення",135)
    url=html.escape(str(item.get("url") or ""),quote=True)
    return f'<a href="{url}"><b>{e(name)}</b></a>'

def geo_url(item):
    c=item.get("coordinates") or {}
    la,lo=c.get("lat"),c.get("lon")
    if not (isinstance(la,(int,float)) and isinstance(lo,(int,float)) and -90<=la<=90 and -180<=lo<=180):
        return None
    return "https://www.google.com/maps/search/?api=1&query="+quote(f"{la:.6f},{lo:.6f}")

def brief_caption(item):
    place=", ".join(str(p) for p in (item.get("city"),item.get("country")) if p)
    grade=quality.priority(item)
    row=[
        link(item),
        ({"reviewing":"⏸ <b>Заявки розглядаються</b>","confirmed":"✅ <b>Сіттера обрано</b>","removed":"⛔️ <b>Ці дати прибрано</b>"}.get(item.get("status")) or ""),
        ("📍 <a href="+chr(34)+html.escape(geo_url(item),quote=True)+chr(34)+"><b>"+e(place)+"</b></a>") if geo_url(item) else "📍 <b>"+e(place)+"</b>",
        f"🗓 <b>{e(item.get('start'))} — {e(item.get('end'))}</b> · {e(item.get('nights'))} ночей",
        "🐾 <b>"+e(oldfmt.pets_label(item))+"</b>"+(
             " · "+e(", ".join(str(x.get("name")) for x in item.get("pet_profiles") or [] if x.get("name"))[:85])
             if any(x.get("name") for x in item.get("pet_profiles") or []) else ""),
        "🚆 "+("Громадський транспорт є" if item.get("transport_accessible") else "Транспорт уточнити")
          +"   📶 "+e(oldfmt.wifi_label(item)),
    ]
    if item.get("pet_tier")=="B":
        row.insert(1,"🐕 <b>Запасний варіант із собаками</b>")
    elif item.get("pet_tier")=="A" and not (item.get("pets") or {}).get("cat"):
        row.insert(1,"🐹 <b>Невеликі домашні тварини</b>")
    left=oldfmt.time_label(item)
    if left:row.append("⏱ <b>Можна залишити:</b> "+e(left))
    flags=grade["flags"]
    if flags:row.append("⚠️ <b>Зверни увагу:</b> "+e("; ".join(f["label"].split(" ",1)[-1] for f in flags[:3])))
    info=oldfmt.brief(item.get("pet_care") or item.get("responsibilities"),155)
    if info:row.append("📝 <b>Догляд:</b> "+e(info))
    if isinstance(item.get("application_count"),int):row.append("✉️ <b>Заявок:</b> "+str(item["application_count"]))
    # If HTML length (including tags) exceeds limit, trim optional lines.
    while len("\n".join(row))>CAP_LIMIT and len(row)>5:
        # Duties then applicants are least important relative to title/status.
        removable=next((i for i,s in enumerate(row) if "📝" in s),None)
        if removable is None:removable=len(row)-1
        row.pop(removable)
    return "\n".join(row)

def _split_plain(text,maxchars=590):
    text=oldfmt.normalize_source(text)
    pieces=[]
    for paragraph in text.split("\n"):
        if not paragraph.strip():continue
        part=paragraph.strip()
        while len(part)>maxchars:
            pos=max(part.rfind(". ",0,maxchars),part.rfind("; ",0,maxchars),part.rfind("! ",0,maxchars))
            if pos<150:pos=part.rfind(" ",0,maxchars)
            if pos<130:pos=maxchars
            else:pos+=1
            pieces.append(part[:pos].strip())
            part=part[pos:].lstrip()
        if part:pieces.append(part)
    return pieces

def detail_pages(item):
    """Each HTML caption is standalone, formatted and under 1024 chars."""
    header=link(item)
    place=", ".join(str(p) for p in (item.get("city"),item.get("country")) if p)
    if place and geo_url(item):
        header+='\n📍 <a href="'+html.escape(geo_url(item),quote=True)+'"><b>'+e(place)+'</b></a>'
    chunks=[]
    for title,body in oldfmt.sections(item):
        for i,segment in enumerate(_split_plain(body)):
            h="<b>"+e(title)+("</b>" if i==0 else " · продовження</b>")
            chunks.append(h+"\n"+e(segment))
    pages=[]
    buf=[]
    def render(parts):
        return header+"\n\n"+"\n\n".join(parts)
    for chunk in chunks:
        if buf and len(render(buf+[chunk]))>CAP_LIMIT:
            pages.append(render(buf));buf=[]
        if len(render([chunk]))>CAP_LIMIT:
            # Extremely long source with XML-escaped symbols; split safely.
            plain=html.unescape(chunk.split("\n",1)[-1])
            title=chunk.split("\n",1)[0]
            for txt in _split_plain(plain,400):
                cand=title+"\n"+e(txt)
                if buf:pages.append(render(buf));buf=[]
                pages.append(render([cand]))
        else:buf.append(chunk)
    if buf:pages.append(render(buf))
    return pages or [header]

def controls(item,mode="short",page=0,photo=0,applied=False,total=None):
    """Stable simple keyboard: no repeated editing of photo/text captions."""
    aid=str(item["assignment_id"])
    count=len(item.get("photo_urls") or [])
    rows=[[{"text":"📖 Надіслати повний опис","callback_data":f"t3:d:{aid}"}]]
    if count:
        rows.append([{"text":f"🖼 Усі фото ({count})","callback_data":f"t3:g:{aid}"}])
    rows.append([{"text":"✅ Заявку подано" if applied else "📨 Я подав заявку",
                  "callback_data":f"t3:a:{aid}"}])
    rows.append([{"text":"🏠 Мене підтвердили","callback_data":f"t3:k:{aid}"}])
    return json.dumps({"inline_keyboard":rows},ensure_ascii=False)

def parse(data):
    data=str(data or "")
    match=re.fullmatch(r"t3:(d|g|a|k):([0-9]{1,15})",data)
    if match:return match.group(1),match.group(2),None,0
    m=re.fullmatch(r"t2:(p|f|a):([0-9]{1,15}):(s|[0-9]{1,3}):([0-9]{1,5})",data)
    if m:
        action,aid,n,p=m.groups()
        return action,aid,None if n=="s" else int(n),int(p)
    m=re.fullmatch(r"t2:c:([0-9]{1,15}):([0-9]{1,5})",data)
    if m:return "c",m.group(1),None,int(m.group(2))
    m=re.fullmatch(r"t2:n:([0-9]{1,15})",data)
    if m:return "n",m.group(1),None,0
    return None

def caption(item,mode="short",page=0,pages=None):
    if mode=="short":return brief_caption(item)
    pages=pages if pages is not None else detail_pages(item)
    n=min(max(0,int(page)),len(pages)-1)
    body=pages[n]+f"\n\n<i>Сторінка {n+1} / {len(pages)}</i>"
    if len(body)>1024:raise ValueError("Telegram photo caption too long")
    return body

def cover(item,index=0):
    photos=[p for p in (item.get("photo_urls") or [])
            if isinstance(p,str) and p.startswith("https://res.cloudinary.com/trustedhousesitters/image/upload/")]
    if not photos:return None
    return photos[min(max(index,0),len(photos)-1)]
