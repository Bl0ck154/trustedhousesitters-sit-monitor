"""Deterministic, non-AI flags and sit priority grounded in public listing text."""
import re

FLAGS = [
 ("💊 Можливі ліки/особливий догляд", r"\b(?:medicat(?:ion|e|ed)|insulin|injection|special medical|pill(?:s)?)\b"),
 ("🚗 Може вимагатися авто", r"\b(?:must have (?:a |your own )?car|car (?:is )?(?:essential|required|necessary)|need (?:your own|a) car|no public transport)\b"),
 ("🍽 Часте годування", r"\b(?:[3-9]\s*[-–]\s*[4-9]|[3-9])\s*(?:times|x)\s*(?:a|per|each)\s*day\b|\b(?:three|four|five)\s+times\s+(?:a|per)\s+day\b"),
 ("🌙 Ночівля/постійна присутність", r"\b(?:cannot be left alone|can't be left alone|not be left alone|overnight care|do not leave.*overnight)\b"),
 ("🚶 Регулярні прогулянки", r"\b(?:daily walks|walk(?:ed|ing)?\s+(?:two|three|twice|three times)\s+(?:a|per)\s+day)\b")
]

def evidence_flags(item):
 text="\n".join(str(item.get(k) or "") for k in ("responsibilities","pet_care","introduction"))
 out=[]
 for label,pat in FLAGS:
  m=re.search(pat,text,re.I)
  if m and not ("авто" in label and text[max(0,m.start()-18):m.start()].lower().rstrip().endswith("no")):
   out.append({"label":label,"excerpt":text[max(0,m.start()-45):min(len(text),m.end()+75)].replace("\n"," ").strip()})
 return out

def priority(item):
 score=int(item.get("score") or 0)
 counts=item.get("pets") or {}
 cats=int(counts.get("cat",item.get("cats") or 0))
 others=sum(int(v or 0) for k,v in counts.items() if k!="cat")
 if cats and not others:score+=15
 if item.get("transport_accessible"):score+=15
 if item.get("internet")=="highSpeed":score+=10
 minutes=item.get("minutes_pet_can_be_left_alone")
 if isinstance(minutes,int) and minutes>=360:score+=8
 if isinstance(item.get("nights"),int):
  score+=min(max(item["nights"]-10,0),15)
 flags=evidence_flags(item)
 if any("ліки" in f["label"] for f in flags):score-=14
 if any("авто" in f["label"] for f in flags):score-=35
 if any("Часте" in f["label"] for f in flags):score-=6
 return {"score":score,"tier":"⭐ Пріоритетний" if score>=100 else "Хороший" if score>=72 else "Звичайний","flags":flags}
