"""On-demand full description and native multi-album gallery for THS Telegram bot.

No editMessageCaption or editMessageMedia: original short photo card remains
unchanged. Description is delivered as HTML text (chunked only for Telegram's
4096-character limit). Gallery uses native albums of 2-10 photos, with a
single photo only for the 1-item remainder.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import html
import json
import os
import urllib.error
import urllib.request

import telegram_card as card
import telegram_format as fmt
import telegram_media_cache as cache
import telegram_photo_api as upload
from setup_telegram import api

DESCRIPTION_LIMIT=3540

def full_description(item):
    """Return all owner content with bold headings, preserving paragraph text."""
    title=card.link(item)
    city=", ".join(x for x in (item.get("city"),item.get("country")) if x)
    url=card.geo_url(item)
    loc=(f'📍 <a href="{html.escape(url,quote=True)}">{fmt.esc(city)}</a>' if url else "📍 "+fmt.esc(city))
    header="📖 <b>Повний опис</b>\n"+title+"\n"+loc
    blocks=[]
    seen_instructions=set()
    for heading,body in fmt.sections(item):
        original=fmt.normalize_source(body)
        if heading.startswith('🗺') and original.startswith('[') and original.endswith(']'):
            continue
        if heading.startswith(('📝','🐈')):
            lines=[]
            for raw in original.splitlines():
                line=raw.strip().lstrip('-•* ').strip()
                key=' '.join(line.casefold().split())
                if not key or key in seen_instructions:continue
                seen_instructions.add(key)
                lines.append('• '+line)
            original='\n'.join(lines)
            if not original:continue
        # Break only at paragraph/sentence boundaries where possible. Every
        # word of each original section must be preserved, not summarized.
        # Keep each short section intact, including all its list lines.
        # Keep the entire section grouped; pagination happens only at page boundaries.
        sections=[original]
        if not sections:continue
        for idx,segment in enumerate(sections):
            h=heading if idx==0 else heading+" (продовження)"
            blocks.append("<b>"+fmt.esc(h)+"</b>\n"+fmt.esc(segment))
    pages=[]
    current=header
    for block in blocks:
        if len(current+"\n\n"+block)>DESCRIPTION_LIMIT and current!=header:
            pages.append(current)
            current=header
        if len(header+"\n\n"+block)>DESCRIPTION_LIMIT:
            # Split oversized sections at lines; repeat the heading only on
            # a new Telegram message, never above every single bullet.
            label,txt=block.split("\n",1)
            segment=label
            for raw_line in txt.splitlines():
                units=([fmt.esc(piece) for piece in card._split_plain(
                    html.unescape(raw_line),maxchars=950)]
                    if len(raw_line)>1250 else [raw_line])
                for line in units:
                    if len(header+"\n\n"+segment+"\n"+line)>DESCRIPTION_LIMIT and segment!=label:
                        pages.append(header+"\n\n"+segment)
                        segment=label.replace("</b>"," (далі)</b>")
                    segment+="\n"+line
            current=header+"\n\n"+segment
        else:
            current+="\n\n"+block
    if current!=header or not pages:pages.append(current)
    if len(pages)>1:
        return [pg+f"\n\n<i>Частина {i+1}/{len(pages)}</i>" for i,pg in enumerate(pages)]
    return pages

def send_description(token,chat_id,item,reply_to=None,api_func=api):
    pages=full_description(item)
    mids=[]
    for text in pages:
        args={"chat_id":str(chat_id),"text":text,"parse_mode":"HTML",
              "disable_web_page_preview":"true"}
        if reply_to is not None:
            args["reply_to_message_id"]=str(reply_to)
            args["allow_sending_without_reply"]="true"
        result=api_func(token,"sendMessage",args)
        if not isinstance(result,dict) or not isinstance(result.get("message_id"),int):
            raise RuntimeError("Telegram did not confirm detail message")
        mids.append(result["message_id"])
    return mids

def gallery_buttons(item):
    import telegram_controls as controls
    return controls.keyboard(item)  # for fallback single-photo action if desired

def _build_multipart(fields,files):
    """multipart files of images + a JSON media field."""
    boundary="----THSAlbum"+os.urandom(9).hex()
    blocks=[]
    for key,value in fields.items():
        blocks.append(("--"+boundary+"\r\n").encode())
        blocks.append(('Content-Disposition: form-data; name="'+str(key)+'"\r\n\r\n').encode())
        blocks.append(str(value).encode("utf8"))
        blocks.append(b"\r\n")
    for name,data in files.items():
        blocks.append(("--"+boundary+"\r\n").encode())
        blocks.append(('Content-Disposition: form-data; name="'+name+'"; filename="house.jpg"\r\n').encode())
        blocks.append(b"Content-Type: image/jpeg\r\n\r\n")
        blocks.append(data)
        blocks.append(b"\r\n")
    blocks.append(("--"+boundary+"--\r\n").encode())
    return b"".join(blocks),boundary

def _post_album(token,fields,files):
    data,boundary=_build_multipart(fields,files)
    request=urllib.request.Request(
        "https://api.telegram.org/bot"+token+"/sendMediaGroup",
        method="POST",data=data,
        headers={"Content-Type":"multipart/form-data; boundary="+boundary})
    try:
        with urllib.request.urlopen(request,timeout=16) as stream:
            resp=json.load(stream)
    except urllib.error.HTTPError as ex:
        raise RuntimeError("Telegram HTTP "+str(ex.code)+" on sendMediaGroup") from None
    except (urllib.error.URLError,TimeoutError):
        raise RuntimeError("Telegram album upload unreachable") from None
    if not resp.get("ok"):
        raise RuntimeError("Telegram rejected photo album")
    return resp.get("result")

def _album_batch(token,chat_id,images,reply_to=None,api_func=api,label=None):
    if not 2<=len(images)<=10:raise ValueError("Album requires 2-10 photos")
    pairs=[(image,cache.resolve(image)) for image in images]
    need=[(index,url) for index,(url,reuse) in enumerate(pairs) if url==reuse]
    files={}
    # Download in parallel so 10 photos don't add up to 10× network latency.
    if need:
        with ThreadPoolExecutor(max_workers=min(5,len(need))) as pool:
            futures={pool.submit(upload.fetch_jpeg,url):(index,url) for index,url in need}
            for fut in as_completed(futures):
                index,url=futures[fut]
                files["photo"+str(index)]=fut.result()
    medias=[]
    for index,(url,reuse) in enumerate(pairs):
        value=reuse if reuse!=url else "attach://photo"+str(index)
        d={"type":"photo","media":value}
        if index==0 and label:d["caption"]=label
        medias.append(d)
    fields={"chat_id":str(chat_id),"media":json.dumps(medias,ensure_ascii=False)}
    if reply_to is not None:
        fields["reply_to_message_id"]=str(reply_to)
        fields["allow_sending_without_reply"]="true"
    if files:
        result=_post_album(token,fields,files)
    else:
        result=api_func(token,"sendMediaGroup",fields)
    if not isinstance(result,list) or len(result)!=len(images):
        raise RuntimeError("Telegram returned incomplete photo album")
    for original,message in zip(images,result):
        cache.remember(original,message)
    return [m["message_id"] for m in result if isinstance(m,dict) and isinstance(m.get("message_id"),int)]

def send_gallery(token,chat_id,item,reply_to=None,api_func=api):
    sources=[u for u in (item.get("photo_urls") or [])
             if isinstance(u,str) and upload._safe_photo_url(u)]
    sources=list(dict.fromkeys(sources))
    ids=[]
    total=len(sources)
    if not total:raise RuntimeError("Listing has no available photos")
    for start in range(0,total,10):
        chunk=sources[start:start+10]
        label=f"🖼 {item.get('city') or 'Житло'} · фото {start+1}–{start+len(chunk)} із {total}"
        if len(chunk)==1:
            url=chunk[0]
            fields={"chat_id":str(chat_id),"photo":cache.resolve(url),"caption":label}
            if reply_to is not None:
                fields["reply_to_message_id"]=str(reply_to)
                fields["allow_sending_without_reply"]="true"
            if fields["photo"]==url:
                result=upload.send_photo(token,url,fields)
            else:
                result=api_func(token,"sendPhoto",fields)
            if not isinstance(result,dict) or not isinstance(result.get("message_id"),int):
                raise RuntimeError("Failed to send gallery tail photo")
            cache.remember(url,result)
            ids.append(result["message_id"])
        else:
            ids.extend(_album_batch(token,chat_id,chunk,reply_to=reply_to,api_func=api_func,label=label))
    return ids
