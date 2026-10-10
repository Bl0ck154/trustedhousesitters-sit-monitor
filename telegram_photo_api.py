"""Fast Telegram photo uploads using multipart from trusted THS Cloudinary.

Cloudinary GET is typically sub-second, but Telegram's own remote-URL fetch can
occasionally stall ~20 seconds. Upload photo bytes directly as attach://image
when a reusable bot-scoped file_id is not yet cached.

No files written, 5 MiB read limit, allowlisted remote origin only.
"""
import json
import os
import urllib.request
import urllib.error
import urllib.parse

MAX_BYTES=5*1024*1024

def _safe_photo_url(url):
    parsed=urllib.parse.urlsplit(str(url))
    return (parsed.scheme=="https" and parsed.hostname=="res.cloudinary.com"
            and parsed.path.startswith("/trustedhousesitters/image/upload/")
            and not parsed.username and not parsed.password)

def fetch_jpeg(url):
    if not _safe_photo_url(url):
        raise ValueError("Untrusted photo URL")
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req,timeout=8) as reply:
        # Resolved redirects must still stay on the same host.
        if not _safe_photo_url(reply.url):
            raise ValueError("Unexpected photo redirect")
        data=reply.read(MAX_BYTES+1)
    if len(data)>MAX_BYTES:
        raise ValueError("Photo too large")
    if not data.startswith(b"\xff\xd8\xff"):
        raise ValueError("Photo is not JPEG")
    return data

def _multipart(fields,file_field,data,filename="house.jpg"):
    boundary="----THS"+os.urandom(12).hex()
    out=[]
    for key,value in fields.items():
        out.append(("--"+boundary+"\r\n").encode())
        out.append(('Content-Disposition: form-data; name="'+str(key)+'"\r\n\r\n').encode())
        out.append(str(value).encode("utf-8"))
        out.append(b"\r\n")
    out.append(("--"+boundary+"\r\n").encode())
    out.append(('Content-Disposition: form-data; name="'+file_field+'"; filename="'+filename+'"\r\n').encode())
    out.append(b"Content-Type: image/jpeg\r\n\r\n")
    out.append(data)
    out.append(b"\r\n")
    out.append(("--"+boundary+"--\r\n").encode())
    return b"".join(out),boundary

def _post(token,method,fields,file_field,data):
    body,boundary=_multipart(fields,file_field,data)
    request=urllib.request.Request(
        "https://api.telegram.org/bot"+token+"/"+method,
        data=body,method="POST",
        headers={"Content-Type":"multipart/form-data; boundary="+boundary})
    try:
        with urllib.request.urlopen(request,timeout=15) as resp:
            result=json.load(resp)
    except urllib.error.HTTPError as exc:
        raise RuntimeError("Telegram HTTP "+str(exc.code)+" on "+method) from None
    except (urllib.error.URLError,TimeoutError):
        raise RuntimeError("Telegram upload unreachable on "+method) from None
    if not result.get("ok"):
        raise RuntimeError("Telegram photo upload failed on "+method)
    return result.get("result")

def send_photo(token,url,fields):
    data=fetch_jpeg(url)
    options={k:v for k,v in fields.items() if k!="photo"}
    return _post(token,"sendPhoto",options,"photo",data)

def edit_media(token,url,fields):
    data=fetch_jpeg(url)
    opts={k:v for k,v in fields.items() if k!="media"}
    media=json.loads(fields["media"])
    media["media"]="attach://image"
    opts["media"]=json.dumps(media,ensure_ascii=False)
    return _post(token,"editMessageMedia",opts,"image",data)
