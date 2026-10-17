/* Cloudflare Workers port. LIVE_MODE and SCAN_ENABLED are off by default.
 * No requests to THS, no Telegram delivery, and no webhook registration on staging.
 */
const ORIGIN="https://www.trustedhousesitters.com";
const EUROPE=ORIGIN+"/house-and-pet-sitting-assignments/europe/";
const PREFERRED=new Set(["Portugal","Spain","France","Germany","Netherlands","Belgium"]);
const ALLOWED=new Set([...PREFERRED,"Luxembourg","Austria","Switzerland","Italy","Denmark","Norway","Sweden","Finland","Iceland","Czech Republic","Poland","Slovenia","Croatia","Estonia","Latvia","Lithuania","Hungary","Slovakia","Greece","Malta"]);
const SMALL=new Set(["small pet","rabbit","hamster","guinea pig","guinea-pig","rodent","rat","mouse","gerbil","chinchilla","fish"]);
const HARD=new Set(["horse","farm animal","livestock","reptile"]);
const STAGES=new Set(["applied","talking","confirmed","rejected","withdrawn"]);
const stageLabels={applied:"📨 Подано",talking:"💬 Обговорюємо",confirmed:"🏠 Підтверджено для мене",rejected:"❌ Відмовили",withdrawn:"↩️ Відкликано"};
const now=()=>Date.now(),iso=()=>new Date().toISOString();
const esc=x=>String(x??"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
const dateMs=s=>Date.parse(String(s)+"T00:00:00Z");
const plusDays=(s,n)=>new Date(dateMs(s)+n*864e5).toISOString().slice(0,10);
const diff=(a,b)=>(dateMs(b)-dateMs(a))/864e5;
function vilniusDay(){
  const p=new Intl.DateTimeFormat("en-GB",{timeZone:"Europe/Vilnius",year:"numeric",month:"2-digit",day:"2-digit"}).formatToParts(new Date());
  const g=k=>p.find(x=>x.type===k)?.value;
  return g("year")+"-"+g("month")+"-"+g("day");
}
function vilniusMinute(){const p=new Intl.DateTimeFormat("en-GB",{timeZone:"Europe/Vilnius",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).formatToParts(new Date());return Number(p.find(x=>x.type==="hour")?.value)*60+Number(p.find(x=>x.type==="minute")?.value);}
const positiveId=v=>/^\d{1,15}$/.test(String(v??""));
function petTier(item){
  const pets=item.pets||{},ks=Object.keys(pets).filter(k=>Number(pets[k])>0);
  if(!ks.length||ks.some(k=>HARD.has(k.toLowerCase())))return "C";
  const dogs=Number(pets.dog||0);if(dogs>2)return "C";
  if(ks.some(k=>!SMALL.has(k.toLowerCase())&&!["dog","cat"].includes(k.toLowerCase())))return "C";
  return dogs?"B":"A";
}
const overlaps=(a,b)=>a.start<b.end&&b.start<a.end;
function journey(stays,start,today){
  const finish=plusDays(start,95),gaps=[];let cursor=start;
  for(const s of [...stays].sort((a,b)=>a.start.localeCompare(b.start))){
    if(s.end<=cursor||s.start>=finish)continue;
    if(s.start>cursor)gaps.push([cursor,s.start<finish?s.start:finish]);
    if(s.end>cursor)cursor=s.end;
    if(cursor>=finish)break;
  }
  if(cursor<finish)gaps.push([cursor,finish]);
  const remaining=gaps.filter(([a,b])=>b>today).map(([a,b])=>[a>today?a:today,b]).filter(([a,b])=>a<b);
  const focus=remaining.find(([a,b])=>diff(a,b)>=7)||remaining[0]||null;
  return {start,finish,gaps:remaining,focus,bridges:remaining.filter(([a,b])=>diff(a,b)<7)};
}
function windowFor(stays,start,today){
  const j=journey(stays,start,today),earliest=j.focus?.[0]||today;
  const latest=stays.length?plusDays(earliest,30):plusDays(today,30);
  return [earliest,latest<j.finish?latest:j.finish];
}
function suitable(item,stays,start,today){
  if(item.status!=="open"||petTier(item)==="C"||item.transit_warning||["none","noWifi"].includes(item.internet))return false;
  if(stays.some(x=>overlaps(item,x)))return false;
  const j=journey(stays,start,today);
  return j.gaps.some(([a,b])=>diff(a,b)>=7&&Math.max(0,(Math.min(dateMs(item.end),dateMs(b))-Math.max(dateMs(item.start),dateMs(a)))/864e5)>=7);
}
function urgent(stays,start,today){const a=journey(stays,start,today).focus;return !!(a&&diff(today,a[0])<=9);}
const shouldAlert=(item,stays,start,today)=>suitable(item,stays,start,today)&&(petTier(item)==="A"||(petTier(item)==="B"&&urgent(stays,start,today)));
async function settings(db,key){const r=await db.prepare("SELECT value FROM settings WHERE key=?").bind(key).first();return r?.value??null;}
async function putSetting(db,key,value){await db.prepare("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value").bind(key,String(value)).run();}
async function staysOf(db){
 const saved=(await db.prepare("SELECT * FROM confirmed_stays ORDER BY start").all()).results;
 let provisional=[];try{provisional=JSON.parse(await settings(db,"temporary_confirmed_stays")||"[]");}catch{}
 for(const x of provisional){
   if(!/^\d{4}-\d\d-\d\d$/.test(x.start||"")||!/^\d{4}-\d\d-\d\d$/.test(x.end||"")||x.start>=x.end)continue;
   if(saved.some(s=>s.start===x.start&&s.end===x.end))continue;
   saved.push({start:x.start,end:x.end,city:String(x.city||""),country:String(x.country||""),title:String(x.title||"Confirmed externally")});
 }
 return saved.sort((a,b)=>a.start.localeCompare(b.start));
}
function earliest(env,backup){const d=env.THS_EARLIEST_START||backup||vilniusDay();return /^\d{4}-\d\d-\d\d$/.test(d)?d:vilniusDay();}
async function ctx(env){const [stays,backup]=await Promise.all([staysOf(env.DB),settings(env.DB,"earliest_start_backup")]);const today=vilniusDay(),start=earliest(env,backup);return {stays,today,start,window:windowFor(stays,start,today)};}
class Restricted extends Error{}
async function accessFetch(env,url){
  const u=new URL(url);
  if(u.origin!==ORIGIN||!u.pathname.startsWith("/house-and-pet-sitting-assignments/"))throw new Error("Source not allowed");
  const until=Number(await settings(env.DB,"access_until")||0);
  if(now()<until)throw new Restricted("Cooldown active");
  let res;
  try{res=await fetch(u.toString(),{redirect:"follow",signal:AbortSignal.timeout(12000),headers:{"Accept":"text/html,application/xhtml+xml"}});}
  catch(e){throw new Error("THS transport failure: "+e.name+": "+String(e.message||"").slice(0,180));}
  const finalURL=new URL(res.url||u.toString());
  if(finalURL.origin!==ORIGIN||!finalURL.pathname.startsWith("/house-and-pet-sitting-assignments/")){
    await putSetting(env.DB,"access_until",now()+21600e3);
    throw new Restricted("Source redirected outside public listing pages");
  }
  if(res.status===403||res.status===429){await putSetting(env.DB,"access_until",now()+(res.status===429?3600e3:21600e3));throw new Restricted("THS "+res.status);}
  if(!res.ok)throw new Error("THS "+res.status);
  const html=await res.text();
  if(/captcha|cloudflare challenge|verify you are human|just a moment/i.test(html.slice(0,12000))){await putSetting(env.DB,"access_until",now()+21600e3);throw new Restricted("THS security challenge");}
  // Restrict diagnostics to public document shape; never persist page HTML or personal identifiers.
  const title=(html.match(/<title[^>]*>([^<]*)<\/title>/i)?.[1]||"").trim().slice(0,90);
  const scriptIds=[...html.matchAll(/<script\b[^>]*\bid\s*=\s*["']([^"']+)["']/gi)].slice(0,12).map(x=>x[1]);
  const match=html.match(/<script\b[^>]*\bid\s*=\s*["']__INITIAL_STATE__["'][^>]*>([\s\S]*?)<\/script>/i);
  if(!match){
    const snippet=html.replace(/<script[^>]*>[\s\S]*?<\/script>/gi,"").replace(/<[^>]*>/g," ").replace(/\s+/g," ").trim().slice(0,220);
    await putSetting(env.DB,"last_source_shape",JSON.stringify({status:res.status,length:html.length,title,scriptIds,contentType:res.headers.get("content-type"),server:res.headers.get("server"),snippet,nextData:html.includes("__NEXT_DATA__"),nuxt:html.includes("__NUXT__"),initialState:html.includes("__INITIAL_STATE__")}));
    if(/access denied|forbidden|request rejected|one more step|checking your browser|security check/i.test(title)){
      await putSetting(env.DB,"access_until",now()+21600e3);
      throw new Restricted("Source access page; 6h cooldown");
    }
    throw new Error("THS structured state unavailable");
  }
  const data=JSON.parse(match[1]);
  if(!data||!data.search)throw new Error("THS state structure changed");
  return data;
}
function searchURL(page,reviewing,context){
  const q={filters:{activeMembership:true,assignments:{dateFrom:context.window[0],dateTo:plusDays(context.window[1],50),reviewing,confirmed:false,durationInDays:{minimum:7,maximum:50}}},facets:[],sort:[{published:"desc"}],page,resultsPerPage:12,debug:false,stats:[]};
  return EUROPE+"?q="+encodeURIComponent(btoa(JSON.stringify(q)));
}
function fingerprint(item,row,status){
  const pets={};for(const a of item.animals||[]){const k=a.slug||a.name||"other";pets[k]=(pets[k]||0)+Number(a.count||0);}
  const hf=item.homeFeatures||[],t=[hf,item.amenities,item.introduction,item.localAttractions,item.responsibilities].map(x=>typeof x==="string"?x:JSON.stringify(x||"")).join(" ").toLowerCase();
  const country=item.location?.countryName;
  const internet=item.wifiAvailable||(typeof item.amenities==="object"?item.amenities?.wifiType:null);
  const out={listing_id:String(item.id),assignment_id:String(row.id),url:ORIGIN+"/house-and-pet-sitting-assignments/l/"+item.id+"/",title:item.title||"",city:item.location?.name||"",country,start:row.startDate,end:row.endDate,nights:diff(row.startDate,row.endDate),pets,cats:pets.cat||0,dogs:pets.dog||0,status,application_count:row.applicationsCount,transit_warning:hf.includes("isNotAccessibleByPublicTransport")||t.includes("not accessible by public transport"),transport_accessible:hf.includes("isAccessibleByPublicTransport"),internet,minutes_pet_can_be_left_alone:item.minutesPetCanBeLeftAlone||null,verified_by_detail:false,eligible_alert:false};
  out.pet_tier=petTier(out);return out;
}
function rowStatus(row,section){
  if(row.isConfirmed)return "confirmed";
  if(row.isReviewing)return "reviewing";
  return ["publishedAssignment","openAssignments"].includes(section)?"open":"unknown";
}
function photoURLs(photos){
  const ids=[];for(const p of [...(photos||[])].sort((a,b)=>Number(!!b.coverPhoto)-Number(!!a.coverPhoto))){
    const id=String(p.publicId||"");
    if(!/^remote_media\/media\/photo\/[a-zA-Z0-9/_-]+(?:\.(?:jpe?g|png|webp))?$/.test(id))continue;
    const u="https://res.cloudinary.com/trustedhousesitters/image/upload/t_highres_2mp,f_auto/v1/"+id;
    if(!ids.includes(u))ids.push(u);
  }return ids;
}
function enrich(out,item){
  const petPhotos=(item.pets||[]).flatMap(p=>p.photos||[]);
  const pet=photoURLs(petPhotos),images=photoURLs(item.photos||[]);
  const lat=item.location?.coordinates?.lat,lon=item.location?.coordinates?.lon;
  const coordinates=typeof lat==="number"&&typeof lon==="number"&&lat>=-90&&lat<=90&&lon>=-180&&lon<=180?{lat,lon,precision:"locality"}:undefined;
  return {...out,coordinates,photo_urls:images.filter(x=>!pet.includes(x)),pet_photo_urls:pet,introduction:String(item.introduction||""),responsibilities:String(item.responsibilities||""),pet_care:String(item.petCareResponsibilities||""),local_attractions:String(item.localAttractions||""),home_features:item.homeFeatures||[],amenities:item.amenities||{},pet_profiles:(item.pets||[]).map(p=>({name:p.name,description:p.description,yearOfBirth:p.yearOfBirth})),owner_name:item.ownerName,home_type:item.homeType,car_included:item.carIncluded,source_published_at:item.publishedDate};
}
async function detail(env,candidate,context){
  const state=await accessFetch(env,candidate.url);
  const listing=state.search?.listing?.[String(candidate.listing_id)];
  if(!listing)throw new Error("THS listing missing");
  const same=[];
  for(const section of ["publishedAssignment","openAssignments","upcomingAssignments","pastAssignments"]){
    for(const row of listing[section]||[]){if(String(row.id)===String(candidate.assignment_id))same.push({section,row});}
  }
  if(!same.length){
    const pathname=state.router?.location?.pathname||"";
    if(!pathname.endsWith("/l/"+candidate.listing_id+"/"))throw new Error("Assignment absent from noncanonical listing page");
    return {...candidate,status:"removed",verified_by_detail:true,eligible_alert:false};
  }
  const flags=new Set(same.map(({row})=>String(!!row.isConfirmed)+":"+String(!!row.isReviewing)));
  const applies=new Set(same.map(x=>x.row.canApply).filter(x=>typeof x==="boolean"));
  const chosen=same[0];
  const status=flags.size>1||applies.size>1?"unknown":rowStatus(chosen.row,chosen.section);
  const real=status==="open"&&applies.size===1&&applies.has(false)?"unknown":status;
  const out=enrich(fingerprint(listing,chosen.row,real),listing);
  out.verified_by_detail=true;out.public_can_apply=applies.size===1?[...applies][0]:null;
  out.eligible_alert=shouldAlert(out,context.stays,context.start,context.today);
  out.observed_at=iso();return out;
}
function priority(item,stays,start,today){
  const tier=petTier(item);
  let score={A:100,B:55,C:0}[tier];
  if(tier==="A"&&Number(item.pets?.cat)>0)score+=12;
  const focus=journey(stays,start,today).focus;
  if(focus&&item.start)score+=Math.max(0,30-Math.abs(diff(focus[0],item.start))*3);
  if(item.transport_accessible)score+=12;
  if(item.internet==="highSpeed")score+=10;
  else if(item.internet==="basic")score+=6;
  if(Number(item.minutes_pet_can_be_left_alone)>=360)score+=8;
  if(item.transit_warning)score-=50;
  if(["Spain","Portugal","France","Germany","Austria"].includes(item.country))score+=4;
  if(stays.length){
    const last=[...stays].sort((a,b)=>b.end.localeCompare(a.end))[0];
    if(item.country===last.country)score+=12;
    else if(({"Germany":["Austria","France","Netherlands","Belgium","Poland","Denmark","Czech Republic","Switzerland"],"Austria":["Germany","Switzerland","Italy","Slovenia","Czech Republic","Hungary"],"France":["Germany","Switzerland","Belgium","Italy","Spain","Luxembourg"],"Spain":["France","Portugal"],"Portugal":["Spain"]}[last.country]||[]).includes(item.country))score+=5;
  }
  const description=[item.responsibilities,item.pet_care,item.introduction].join(" ").toLowerCase();
  if(["must have a car","car required","own car essential","no public transport"].some(x=>description.includes(x)))score-=90;
  if(["medication","insulin","injections","reactive dog","pulls hard","giant dog"].some(x=>description.includes(x)))score-=24;
  if(tier==="B"&&Number(item.pets?.dog)===2)score-=10;
  return score;
}
function validRow(i,row,c){
  const country=i.location?.countryName;const n=diff(row.startDate,row.endDate);
  return ALLOWED.has(country)&&Number.isFinite(n)&&n>=7&&n<=50&&row.startDate>=c.window[0]&&row.startDate<=c.window[1];
}
function searchRows(state,c){
  const list=state.search?.listings?.["search-listings-results"];
  if(!list||!Array.isArray(list.results))throw new Error("THS search format changed");
  const rows=[];
  for(const lid of list.results){
    const item=state.search.listing?.[String(lid)];
    if(!item)continue;
    const seen=new Set();
    for(const key of ["publishedAssignment","openAssignments"]){
      for(const row of item[key]||[]){
        if(!positiveId(row.id)||seen.has(String(row.id))||!validRow(item,row,c))continue;
        seen.add(String(row.id));rows.push(fingerprint(item,row,rowStatus(row,key)));
      }
    }
  }
  return {rows,total:Number(list.total||0),count:list.results.length};
}
async function archive(db,item){
  await db.prepare("INSERT INTO records(assignment_id,status,payload,updated_at) VALUES(?,?,?,?) ON CONFLICT(assignment_id) DO UPDATE SET status=excluded.status,payload=excluded.payload,updated_at=excluded.updated_at")
    .bind(item.assignment_id,item.status,JSON.stringify(item),iso()).run();
}
async function seenCandidate(env,item,c){
  if(item.status!=="open"||!suitable(item,c.stays,c.start,c.today))return;
  const old=await env.DB.prepare("SELECT payload FROM records WHERE assignment_id=?").bind(item.assignment_id).first();
  const saved=old?.payload?JSON.parse(old.payload):null;
  let actual;
  if(saved?.verified_by_detail&&saved.observed_at&&now()-Date.parse(saved.observed_at)<1800e3&&
      ["assignment_id","listing_id","start","end","status","title","application_count","pets","transit_warning"].every(k=>JSON.stringify(saved[k])===JSON.stringify(item[k]))){
    actual={...saved,eligible_alert:shouldAlert(saved,c.stays,c.start,c.today)};
  }else actual=await detail(env,item,c);
  await archive(env.DB,actual);
  if(actual.status!=="open"||!actual.verified_by_detail||!actual.eligible_alert)return;
  const ignored=await env.DB.prepare("SELECT 1 FROM ignored_assignments WHERE assignment_id=?").bind(item.assignment_id).first();
  if(ignored)return;
  const oldDelivered=await env.DB.prepare("SELECT 1 FROM watch WHERE assignment_id=?").bind(item.assignment_id).first();
  if(oldDelivered)return;
  await env.DB.prepare("INSERT OR IGNORE INTO pending_notifications(assignment_id,discovered_at,payload,state) VALUES(?,?,?,'pending')").bind(actual.assignment_id,iso(),JSON.stringify(actual)).run();
}
async function doPage(env,page,reviewing,c){
  const state=await accessFetch(env,searchURL(page,reviewing,c)),data=searchRows(state,c);
  let details=0;
  for(const item of data.rows.sort((a,b)=>(a.status!=="open")-(b.status!=="open")||priority(b,c.stays,c.start,c.today)-priority(a,c.stays,c.start,c.today))){
    if(item.status==="open"&&suitable(item,c.stays,c.start,c.today)&&details<2){
      try{await seenCandidate(env,item,c);details++;}catch(e){if(e instanceof Restricted)throw e;}
    }else{
      const exists=await env.DB.prepare("SELECT status,payload FROM records WHERE assignment_id=?").bind(item.assignment_id).first();
      if(!exists)await archive(env.DB,item);
      else if(exists.status!==item.status){
        const former=JSON.parse(exists.payload);
        await archive(env.DB,{...former,status:item.status,application_count:item.application_count,verified_by_detail:false,eligible_alert:false});
      }
    }
  }
  return data;
}
async function scanQuick(env,c){
  // One page per invocation in Free profile; 3 pages per invocation in full profile.
  const limit=env.SCAN_PROFILE==="quick"?1:3;
  for(let page=1;page<=limit;page++){
    const d=await doPage(env,page,false,c);
    if(!d.count||page*12>=d.total)break;
  }
}
async function scanFull(env,c){
  const cycle=Math.floor(now()/1800e3);
  let progress=JSON.parse(await settings(env.DB,"full_progress")||"null");
  if(!progress||progress.cycle!==cycle)progress={cycle,page:1,reviewing:false,done:false};
  if(progress.done)return;
  for(let k=0;k<7;k++){
    const d=await doPage(env,progress.page,progress.reviewing,c);
    progress.page++;
    if(!d.count||progress.page>90||((progress.page-1)*12>=d.total)){
      if(progress.reviewing){progress.done=true;break;}
      progress.reviewing=true;progress.page=1;
    }
  }
  await putSetting(env.DB,"full_progress",JSON.stringify(progress));
}
function buttons(item,applied=false,ignored=false){
 const id=item.assignment_id,rows=[[{text:"📖 Надіслати повний опис",callback_data:"t3:d:"+id}]];
 if(item.photo_urls?.length)rows.push([{text:"🏡 Фото житла ("+item.photo_urls.length+")",callback_data:"t3:g:"+id}]);
 if(item.pet_photo_urls?.length)rows.push([{text:"🐾 Фото тварин ("+item.pet_photo_urls.length+")",callback_data:"t3:t:"+id}]);
 rows.push([{text:applied?"✅ Заявку подано · скасувати":"📨 Я подав заявку",callback_data:"t3:"+(applied?"u":"a")+":"+id}]);
 if(applied)rows.push([{text:"🏠 Мене підтвердили",callback_data:"t3:k:"+id}]);
 rows.push([{text:ignored?"↩️ Повернути в моніторинг":"🚫 Не цікаво",callback_data:"t3:i:"+id+":"+(ignored?"0":"1")}]);
 return {inline_keyboard:rows};
}
function caption(item){
 const p=Object.entries(item.pets||{}).filter(x=>Number(x[1])>0).map(([k,v])=>v+"×"+k).join(", ")||"—";
 return ("🏠 <b>"+esc(item.city)+", "+esc(item.country)+"</b>\n"+
 "📅 "+esc(item.start)+" — "+esc(item.end)+" ("+Number(item.nights||0)+" ночей)\n"+
 "🐾 "+esc(p)+"\n"+
 "🚍 Транспорт: "+(item.transport_accessible?"так":"не підтверджено")+"\n"+
 "📶 Wi-Fi: "+esc(item.internet||"не підтверджено")+"\n"+
 (Number.isInteger(item.application_count)&&item.application_count>0?"📝 Публічних заявок (може бути застаріло): "+item.application_count+"\n":"")+
 '<a href="'+esc(item.url)+'">Відкрити оголошення</a>').slice(0,1000);
}
async function webhookSecret(env){
 if(env.TELEGRAM_WEBHOOK_SECRET)return env.TELEGRAM_WEBHOOK_SECRET;
 if(!env.TELEGRAM_BOT_TOKEN)throw new Error("Missing bot token");
 // A deterministic webhook-only secret derived from the bot credential.
 // The raw Telegram token is never exposed in webhook URLs or source control.
 const data=new TextEncoder().encode("trustedhousesitters:webhook:v1:"+env.TELEGRAM_BOT_TOKEN);
 const digest=await crypto.subtle.digest("SHA-256",data);
 return Array.from(new Uint8Array(digest),x=>x.toString(16).padStart(2,"0")).join("");
}
async function tg(env,method,payload){
 if(env.LIVE_MODE!=="true"||!env.TELEGRAM_BOT_TOKEN||!env.TELEGRAM_CHAT_ID)throw new Error("Telegram disabled");
 const r=await fetch("https://api.telegram.org/bot"+env.TELEGRAM_BOT_TOKEN+"/"+method,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload),signal:AbortSignal.timeout(12000)});
 if(!r.ok)throw new Error("Telegram HTTP "+r.status);
 const json=await r.json();if(!json.ok)throw new Error("Telegram rejected "+method);
 return json.result;
}
async function sendCard(env,item){
 const id=item.assignment_id;const app=await env.DB.prepare("SELECT 1 FROM applications WHERE assignment_id=? AND stage IN ('applied','talking','confirmed')").bind(id).first();
 const payload={chat_id:env.TELEGRAM_CHAT_ID,parse_mode:"HTML",reply_markup:buttons(item,!!app),disable_notification:false};
 if(item.photo_urls?.length){try{const out=await tg(env,"sendPhoto",{...payload,photo:item.photo_urls[0],caption:caption(item)});return out.message_id;}catch(e){if(!String(e).includes("Telegram HTTP 400"))throw e;}}
 const out=await tg(env,"sendMessage",{...payload,text:caption(item),link_preview_options:{is_disabled:true}});return out.message_id;
}
async function deliver(env,c){
 const q=(await env.DB.prepare("SELECT * FROM pending_notifications WHERE state='pending' ORDER BY discovered_at LIMIT 3").all()).results;
 for(const row of q){
   const ignored=await env.DB.prepare("SELECT 1 FROM ignored_assignments WHERE assignment_id=?").bind(row.assignment_id).first();
   if(ignored){await env.DB.prepare("UPDATE pending_notifications SET state='dismissed' WHERE assignment_id=?").bind(row.assignment_id).run();continue;}
   const old=await env.DB.prepare("SELECT 1 FROM watch WHERE assignment_id=?").bind(row.assignment_id).first();
   if(old){await env.DB.prepare("UPDATE pending_notifications SET state='sent' WHERE assignment_id=?").bind(row.assignment_id).run();continue;}
   const actual=await detail(env,JSON.parse(row.payload),c);
   if(!(actual.status==="open"&&actual.eligible_alert&&actual.verified_by_detail)){
     await env.DB.prepare("UPDATE pending_notifications SET state='stale' WHERE assignment_id=?").bind(row.assignment_id).run();continue;
   }
   // Claim before external send. Ambiguous Telegram timeouts must not cause duplicate sends.
   const claim=await env.DB.prepare("UPDATE pending_notifications SET state='sending' WHERE assignment_id=? AND state='pending'").bind(row.assignment_id).run();
   if(!claim.meta.changes)continue;
   try{
     const mid=await sendCard(env,actual);
     await env.DB.batch([
       env.DB.prepare("UPDATE pending_notifications SET state='sent' WHERE assignment_id=?").bind(row.assignment_id),
       env.DB.prepare("INSERT OR REPLACE INTO watch(assignment_id,status,payload,last_checked,last_change,message_id) VALUES(?,?,?,?,?,?)").bind(row.assignment_id,"open",JSON.stringify(actual),iso(),iso(),mid),
       env.DB.prepare("INSERT OR REPLACE INTO controls(assignment_id,album_message_id,control_message_id,updated_at) VALUES(?,?,?,?)").bind(row.assignment_id,mid,mid,iso())
     ]);
   }catch(e){await env.DB.prepare("UPDATE pending_notifications SET state='uncertain' WHERE assignment_id=?").bind(row.assignment_id).run();throw e;}
 }
}
async function sendStatus(env,item,state,mid){
 const words={reviewing:"⏸ Прийом заявок призупинено",open:"🔔 Заявки знову відкриті",confirmed:"✅ Сіттера обрано",removed:"⛔ Дати прибрано"};
 const lines=[words[state],'<a href="'+esc(item.url)+'"><b>'+esc(item.title||"Оголошення")+'</b></a>'];
 if(item.city||item.country)lines.push("📍 "+esc([item.city,item.country].filter(Boolean).join(", ")));
 if(item.start&&item.end)lines.push("📅 "+esc(item.start)+" — "+esc(item.end));
 if(state==="open"||state==="reviewing")lines.push("📨 Заявок на сайті: "+(Number.isInteger(item.application_count)&&item.application_count>=0?item.application_count:"—"));
 const payload={chat_id:env.TELEGRAM_CHAT_ID,text:lines.join("\n"),parse_mode:"HTML"};
 if(mid)payload.reply_parameters={message_id:mid,allow_sending_without_reply:true};
 try{return (await tg(env,"sendMessage",payload)).message_id;}
 catch(e){if(!mid||!String(e).includes("Telegram HTTP 400"))throw e;delete payload.reply_parameters;return (await tg(env,"sendMessage",payload)).message_id;}
}
async function statusWatch(env,c){
 const rows=(await env.DB.prepare("SELECT * FROM watch WHERE last_checked IS NULL OR last_checked<? ORDER BY COALESCE(last_checked,'') LIMIT 8").bind(new Date(now()-120e3).toISOString()).all()).results;
 for(const row of rows){
   const ignored=await env.DB.prepare("SELECT 1 FROM ignored_assignments WHERE assignment_id=?").bind(row.assignment_id).first();
   if(ignored)continue;
   let base;try{base=JSON.parse(row.payload);}catch{continue;}
   if(base.end<plusDays(c.today,-1))continue;
   const recent=row.last_change&&now()-Date.parse(row.last_change)<86400e3;
   const threshold=row.status==="reviewing"||recent?120e3:240e3;
   if(row.last_checked&&now()-Date.parse(row.last_checked)<threshold)continue;
   let actual;try{actual=await detail(env,base,c);}catch(e){if(e instanceof Restricted)throw e;continue;}
   const instant=iso();
   if(!["open","reviewing","confirmed","removed"].includes(actual.status)){
     await env.DB.prepare("UPDATE watch SET last_checked=? WHERE assignment_id=?").bind(instant,row.assignment_id).run();continue;
   }
   if(actual.status===row.status){
     await env.DB.batch([
       env.DB.prepare("DELETE FROM watch_transitions WHERE assignment_id=?").bind(row.assignment_id),
       env.DB.prepare("UPDATE watch SET payload=?,last_checked=? WHERE assignment_id=?").bind(JSON.stringify(actual),instant,row.assignment_id)
     ]);continue;
   }
   const pending=await env.DB.prepare("SELECT * FROM watch_transitions WHERE assignment_id=?").bind(row.assignment_id).first();
   if(!pending||pending.proposed_status!==actual.status){
     await env.DB.batch([
       env.DB.prepare("INSERT INTO watch_transitions(assignment_id,proposed_status,first_seen,observation_count) VALUES(?,?,?,1) ON CONFLICT(assignment_id) DO UPDATE SET proposed_status=excluded.proposed_status,first_seen=excluded.first_seen,observation_count=1").bind(row.assignment_id,actual.status,instant),
       env.DB.prepare("UPDATE watch SET last_checked=? WHERE assignment_id=?").bind(instant,row.assignment_id)
     ]);continue;
   }
   if(now()-Date.parse(pending.first_seen)<65000||(actual.status==="open"&&pending.observation_count<2)){
     await env.DB.batch([
       env.DB.prepare("UPDATE watch_transitions SET observation_count=observation_count+1 WHERE assignment_id=?").bind(row.assignment_id),
       env.DB.prepare("UPDATE watch SET last_checked=? WHERE assignment_id=?").bind(instant,row.assignment_id)
     ]);continue;
   }
   if(actual.status==="open"){
     if(actual.public_can_apply!==true){await env.DB.prepare("UPDATE watch SET last_checked=? WHERE assignment_id=?").bind(instant,row.assignment_id).run();continue;}
     const applied=await env.DB.prepare("SELECT 1 FROM applications WHERE assignment_id=? AND stage IN ('applied','talking','confirmed')").bind(row.assignment_id).first();
     if(applied){await env.DB.batch([env.DB.prepare("UPDATE watch SET status=?,payload=?,last_checked=?,last_change=? WHERE assignment_id=?").bind("open",JSON.stringify(actual),instant,instant,row.assignment_id),env.DB.prepare("DELETE FROM watch_transitions WHERE assignment_id=?").bind(row.assignment_id)]);continue;}
   }
   const parent=await env.DB.prepare("SELECT control_message_id,album_message_id FROM controls WHERE assignment_id=?").bind(row.assignment_id).first();
   await sendStatus(env,actual,actual.status,parent?.control_message_id||parent?.album_message_id||row.message_id);
   await env.DB.batch([
     env.DB.prepare("UPDATE watch SET status=?,payload=?,last_checked=?,last_change=? WHERE assignment_id=?").bind(actual.status,JSON.stringify(actual),instant,instant,row.assignment_id),
     env.DB.prepare("DELETE FROM watch_transitions WHERE assignment_id=?").bind(row.assignment_id)
   ]);
 }
}
function listingLink(item){return '<a href="'+esc(item.url||"")+'">'+esc(item.title||item.assignment_id)+'</a>';}
async function recentCandidates(env,c){
 const rows=(await env.DB.prepare("SELECT payload FROM records ORDER BY updated_at DESC LIMIT 200").all()).results;
 const ignored=new Set((await env.DB.prepare("SELECT assignment_id FROM ignored_assignments").all()).results.map(x=>x.assignment_id));
 const items=rows.map(r=>{try{return JSON.parse(r.payload);}catch{return null;}}).filter(x=>x&&!ignored.has(x.assignment_id)&&suitable(x,c.stays,c.start,c.today));
 return items.sort((a,b)=>Number(petTier(a)==="B")-Number(petTier(b)==="B")||priority(b,c.stays,c.start,c.today)-priority(a,c.stays,c.start,c.today));
}
async function reportText(env,kind,c){
 const apps=(await env.DB.prepare("SELECT * FROM applications ORDER BY applied_at DESC LIMIT 40").all()).results;
 const j=journey(c.stays,c.start,c.today);
 if(kind==="plan"){
   const text=["🏠 <b>План житла</b>","Початок пошуку: <b>"+esc(c.start)+"</b> · горизонт 95 днів"];
   if(!c.stays.length)text.push("🔴 <b>Підтверджених проживань ще немає.</b>");
   else text.push("✅ <b>Підтверджено вручну:</b>",...c.stays.map(x=>"• "+esc(x.start)+"–"+esc(x.end)+" · "+esc(x.city)+", "+esc(x.country)));
   if(j.focus)text.push("🎯 Наступне вікно: <b>"+j.focus[0]+" — "+j.focus[1]+"</b>","⏳ До початку: <b>"+Math.max(0,diff(c.today,j.focus[0]))+" днів</b>");
   for(const [a,b] of j.bridges.slice(0,3))text.push("⚠️ Прогалина <b>"+diff(a,b)+" ночей</b> ("+a+"–"+b+")");
   text.push("🐕 Резерв із собаками: "+(urgent(c.stays,c.start,c.today)?"активні сповіщення":"окремий список /options"));return text.join("\n").slice(0,3950);
 }
 if(kind==="applications"){
   if(!apps.length)return "📋 <b>Заявки</b>\nПоки немає відмічених заявок.";
   const lines=["📋 <b>Мої заявки</b> · статуси позначаються вручну"];
   for(const a of apps.slice(0,20)){
     const w=await env.DB.prepare("SELECT payload,status FROM watch WHERE assignment_id=?").bind(a.assignment_id).first();
     const r=await env.DB.prepare("SELECT payload,status FROM records WHERE assignment_id=?").bind(a.assignment_id).first();
     const item=JSON.parse(w?.payload||r?.payload||"{}");
     lines.push("• "+listingLink({...item,assignment_id:a.assignment_id})+"\n  "+esc(item.city)+" · "+esc(item.start||"?")+"–"+esc(item.end||"?")+"\n  "+stageLabels[a.stage]+" · ID: <code>"+esc(a.assignment_id)+"</code> · стан оголошення: "+esc(w?.status||r?.status||"невідомий"));
   }return lines.join("\n").slice(0,3950);
 }
 const items=await recentCandidates(env,c),a=items.filter(x=>petTier(x)==="A"),b=items.filter(x=>petTier(x)==="B");
 if(kind==="options"){
   const out=["🔎 <b>Варіанти житла</b>","🐈 Коти / дрібні тварини: <b>"+a.length+"</b> · 🐕 Собаки (резерв): <b>"+b.length+"</b>"];
   for(const [label,group] of [["Пріоритетні",a],["Запасні",b]]){
     if(!group.length)continue;out.push("<b>"+label+"</b>");
     for(const item of group.slice(0,5))out.push("• "+listingLink(item)+" — "+esc(item.city)+" · "+esc(item.start)+"–"+esc(item.end)+" · ID: <code>"+item.assignment_id+"</code>");
   }
   if(!items.length)out.push("Зараз у збереженій вибірці немає придатних варіантів.");return out.join("\n").slice(0,3950);
 }
 const counts={};for(const x of apps)counts[x.stage]=(counts[x.stage]||0)+1;
 const out=["☀️ <b>Житло · "+c.today+"</b>"];
 if(j.focus)out.push("⏳ Наступна незакрита дата: <b>"+j.focus[0]+"</b> · "+Math.max(0,diff(c.today,j.focus[0]))+" днів");
 out.push("📨 Подано: "+(counts.applied||0)+" · 💬 Відповіли: "+(counts.talking||0)+" · ✅ Підтверджено: "+c.stays.length+" · ❌ Відмовили: "+(counts.rejected||0));
 out.push("🐈 Основні: <b>"+a.length+"</b> · 🐕 Резерв: <b>"+b.length+"</b>");
 for(const item of items.slice(0,3))out.push("• "+(petTier(item)==="B"?"🐕 резерв · ":"")+listingLink(item)+" — "+esc(item.city)+", "+esc(item.start));
 return out.join("\n").slice(0,3950);
}
async function updateStage(env,aid,target){
 if(!positiveId(aid)||!STAGES.has(target))throw new Error("Невідомий статус або ID");
 const w=await env.DB.prepare("SELECT payload FROM watch WHERE assignment_id=?").bind(aid).first();
 const r=await env.DB.prepare("SELECT payload FROM records WHERE assignment_id=?").bind(aid).first();
 const item=JSON.parse(w?.payload||r?.payload||"null");if(!item)throw new Error("Невідоме оголошення");
 const old=await env.DB.prepare("SELECT stage FROM applications WHERE assignment_id=?").bind(aid).first();
 if(target==="confirmed"){
   if(!["applied","talking","confirmed"].includes(old?.stage))throw new Error("Спочатку познач заявку як подану");
   if(!item.start||!item.end||item.start>=item.end)throw new Error("Некоректні дати");
   const conf=(await env.DB.prepare("SELECT * FROM confirmed_stays WHERE assignment_id!=?").bind(aid).all()).results;
   if(conf.some(x=>overlaps(item,x)))throw new Error("Цей сіт перетинається з уже підтвердженим");
 }
 await env.DB.batch([
   env.DB.prepare("INSERT INTO applications(assignment_id,applied_at,stage) VALUES(?,?,?) ON CONFLICT(assignment_id) DO UPDATE SET stage=excluded.stage").bind(aid,iso(),target),
   target==="confirmed"?env.DB.prepare("INSERT INTO confirmed_stays(assignment_id,start,end,city,country,title,confirmed_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(assignment_id) DO UPDATE SET start=excluded.start,end=excluded.end,city=excluded.city,country=excluded.country,title=excluded.title,confirmed_at=excluded.confirmed_at").bind(aid,item.start,item.end,item.city||"",item.country||"",item.title||"",iso()):env.DB.prepare("DELETE FROM confirmed_stays WHERE assignment_id=?").bind(aid)
 ]);
 return target;
}
async function snapshot(env,aid){const w=await env.DB.prepare("SELECT payload FROM watch WHERE assignment_id=?").bind(aid).first(),r=w?null:await env.DB.prepare("SELECT payload FROM records WHERE assignment_id=?").bind(aid).first();return JSON.parse(w?.payload||r?.payload||"null");}
async function redraw(env,aid,mid){
 const item=await snapshot(env,aid);if(!item)return;
 const applied=await env.DB.prepare("SELECT 1 FROM applications WHERE assignment_id=? AND stage IN ('applied','talking','confirmed')").bind(aid).first();
 const ignored=await env.DB.prepare("SELECT 1 FROM ignored_assignments WHERE assignment_id=?").bind(aid).first();
 try{await tg(env,"editMessageReplyMarkup",{chat_id:env.TELEGRAM_CHAT_ID,message_id:mid,reply_markup:buttons(item,!!applied,!!ignored)});}catch{/* Database is the source of truth. Retry on next action. */}
}
async function description(env,item){
 const parts=[["🏠","Про житло",item.introduction],["🐾","Догляд за тваринами",item.pet_care],["📋","Обов'язки",item.responsibilities],["🌍","Околиця",item.local_attractions]];
 for(const [emoji,title,v] of parts){
   if(!v)continue;
   for(let i=0;i<v.length;i+=3400)await tg(env,"sendMessage",{chat_id:env.TELEGRAM_CHAT_ID,text:emoji+" <b>"+title+"</b>\n"+esc(v.slice(i,i+3400)),parse_mode:"HTML",link_preview_options:{is_disabled:true}});
 }
}
async function gallery(env,item,type,c){
 const updated=await detail(env,item,c);const urls=type==="g"?updated.photo_urls:updated.pet_photo_urls;
 if(!urls?.length){await tg(env,"sendMessage",{chat_id:env.TELEGRAM_CHAT_ID,text:"Фотографії недоступні"});return;}
 for(let i=0;i<Math.min(urls.length,30);i+=10){
   const arr=urls.slice(i,i+10);
   if(arr.length===1)await tg(env,"sendPhoto",{chat_id:env.TELEGRAM_CHAT_ID,photo:arr[0]});
   else await tg(env,"sendMediaGroup",{chat_id:env.TELEGRAM_CHAT_ID,media:arr.map(x=>({type:"photo",media:x}))});
 }
}
async function telegramUpdate(env,update){
 const id=update.update_id;
 if(!Number.isSafeInteger(id))return;
 const message=update.message||update.callback_query?.message||{};
 const actor=update.callback_query?.from||update.message?.from||{};
 if(message.chat?.type!=="private"||String(message.chat.id)!==String(env.TELEGRAM_CHAT_ID)||String(actor.id)!==String(env.TELEGRAM_CHAT_ID))return;
 const claim=await env.DB.prepare("INSERT OR IGNORE INTO telegram_updates(update_id,received_at) VALUES(?,?)").bind(id,iso()).run();
 if(!claim.meta.changes)return;
 const c=await ctx(env);
 if(update.message){
   const args=String(update.message.text||"").trim().split(/\s+/),cmd=(args[0]||"").split("@")[0].toLowerCase();
   if(!["/start","/help","/plan","/options","/report","/applications","/zayavki","/applied","/talking","/confirm","/reject","/withdraw","/status"].includes(cmd))return;
   let body="";
   if(cmd==="/plan"||cmd==="/options"||cmd==="/report")body=await reportText(env,cmd.slice(1),c);
   else if(cmd==="/applications"||cmd==="/zayavki")body=await reportText(env,"applications",c);
   else if(cmd==="/start"||cmd==="/help")body="🏠 <b>Монітор житла</b>\n/plan — план і прогалини\n/options — варіанти\n/applications — заявки\n/report — звіт\n/applied ID · /talking ID · /confirm ID · /reject ID · /withdraw ID";
   else{
     const stages={"/applied":"applied","/talking":"talking","/confirm":"confirmed","/reject":"rejected","/withdraw":"withdrawn"};
     const aid=args[1],target=cmd==="/status"?args[2]:stages[cmd];
     try{await updateStage(env,aid,target);body="✅ "+esc(aid)+": "+stageLabels[target];}catch(e){body="⚠️ "+esc(e.message);}
   }
   await tg(env,"sendMessage",{chat_id:env.TELEGRAM_CHAT_ID,text:body,parse_mode:"HTML",reply_parameters:{message_id:message.message_id,allow_sending_without_reply:true}});return;
 }
 const cb=update.callback_query,data=String(cb?.data||""),mid=message.message_id;
 if(!cb||!Number.isInteger(mid))return;
 // ACK immediately. Do not permit repeated updates to resend galleries.
 await tg(env,"answerCallbackQuery",{callback_query_id:cb.id});
 let m=data.match(/^t3:(d|g|t|a|u|k):(\d{1,15})$/),ignore=data.match(/^t3:i:(\d{1,15}):([01])$/),confirmation=data.match(/^t4:([yn]):(\d{1,15})$/);
 if(confirmation){
   const [,flag,aid]=confirmation;
   const pending=await env.DB.prepare("SELECT * FROM pending_confirmations WHERE prompt_message_id=? AND assignment_id=?").bind(mid,aid).first();
   if(!pending||now()-Number(pending.created_at)*1000>600e3)return;
   const del=await env.DB.prepare("DELETE FROM pending_confirmations WHERE prompt_message_id=? AND assignment_id=?").bind(mid,aid).run();
   if(!del.meta.changes)return;
   let text="Скасовано.";
   if(flag==="y"){try{await updateStage(env,aid,"confirmed");text="✅ Проживання підтверджено.";}catch(e){text="⚠️ "+esc(e.message);}}
   await tg(env,"sendMessage",{chat_id:env.TELEGRAM_CHAT_ID,text,parse_mode:"HTML",reply_parameters:{message_id:mid,allow_sending_without_reply:true}});
   return;
 }
 if(ignore){
   const [,aid,value]=ignore;await env.DB.prepare(value==="1"?"INSERT OR IGNORE INTO ignored_assignments(assignment_id,reason,updated_at) VALUES(?,'not_interested',?)":"DELETE FROM ignored_assignments WHERE assignment_id=?").bind(...(value==="1"?[aid,iso()]:[aid])).run();
   await redraw(env,aid,mid);return;
 }
 if(!m)return;
 const [,action,aid]=m;const item=await snapshot(env,aid);if(!item)return;
 const card=await env.DB.prepare("SELECT message_id FROM watch WHERE assignment_id=?").bind(aid).first();
 const control=await env.DB.prepare("SELECT album_message_id,control_message_id FROM controls WHERE assignment_id=?").bind(aid).first();
 const alias=await env.DB.prepare("SELECT 1 FROM control_instances WHERE assignment_id=? AND message_id=?").bind(aid,mid).first();
 if(!([card?.message_id,control?.album_message_id,control?.control_message_id].some(x=>Number(x)===mid)||alias))return;
 if(["d","g","t"].includes(action)){
   const t=now()/1000,interval=action==="d"?30:120;
   const claim=await env.DB.prepare("INSERT INTO button_sends(assignment_id,message_id,action,sent_at,state) VALUES(?,?,?,?,'sending') ON CONFLICT(assignment_id,message_id,action) DO UPDATE SET sent_at=excluded.sent_at,state='sending' WHERE button_sends.sent_at<?")
     .bind(aid,mid,action,t,t-interval).run();
   if(!claim.meta.changes)return;
   try{
     if(action==="d")await description(env,item);
     else await gallery(env,item,action,c);
     await env.DB.prepare("UPDATE button_sends SET state='sent' WHERE assignment_id=? AND message_id=? AND action=?").bind(aid,mid,action).run();
   }catch(e){
     await env.DB.prepare("UPDATE button_sends SET state='uncertain' WHERE assignment_id=? AND message_id=? AND action=?").bind(aid,mid,action).run();
     throw e;
   }
   return;
 }
 if(action==="a"){await updateStage(env,aid,"applied");await redraw(env,aid,mid);return;}
 if(action==="u"){await env.DB.batch([env.DB.prepare("DELETE FROM applications WHERE assignment_id=?").bind(aid),env.DB.prepare("DELETE FROM confirmed_stays WHERE assignment_id=?").bind(aid)]);await redraw(env,aid,mid);return;}
 if(action==="k"){
   const app=await env.DB.prepare("SELECT stage FROM applications WHERE assignment_id=?").bind(aid).first();
   if(!["applied","talking"].includes(app?.stage))return;
   const msg=await tg(env,"sendMessage",{chat_id:env.TELEGRAM_CHAT_ID,text:"🏠 <b>Підтвердити власне проживання?</b>\n"+esc(item.city)+", "+esc(item.country)+"\n📅 "+esc(item.start)+"–"+esc(item.end),parse_mode:"HTML",reply_markup:{inline_keyboard:[[{text:"✅ Так, мене підтвердили",callback_data:"t4:y:"+aid},{text:"Скасувати",callback_data:"t4:n:"+aid}]]},reply_parameters:{message_id:mid,allow_sending_without_reply:true}});
   await env.DB.prepare("INSERT OR REPLACE INTO pending_confirmations(prompt_message_id,assignment_id,created_at) VALUES(?,?,?)").bind(msg.message_id,aid,now()/1000).run();
 }
}
async function acquire(env,key,seconds){
 const t=now();const r=await env.DB.prepare("INSERT INTO leases(name,expires_at) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET expires_at=excluded.expires_at WHERE leases.expires_at<?").bind(key,t+seconds*1000,t).run();
 return !!r.meta.changes;
}
async function release(env,key){await env.DB.prepare("UPDATE leases SET expires_at=0 WHERE name=?").bind(key).run();}
async function scheduler(env,controller){
 if(env.SCAN_ENABLED!=="true")return;
 const minute=Math.floor(now()/60000);
 if(!(await acquire(env,"cron",55)))return;
 await putSetting(env.DB,"last_cron_tick",iso());
 try{
   const c=await ctx(env);
   if(minute%2===0){
     try{await scanQuick(env,c);await putSetting(env.DB,"last_quick_success",iso());}
     catch(e){await putSetting(env.DB,"last_quick_error",String(e.name||"Error")+": "+String(e.message||"").slice(0,160));if(e instanceof Restricted)return;console.warn("quick scan failed",e.name);}
   }
   if(env.SCAN_PROFILE!=="quick"){
     try{await scanFull(env,c);await putSetting(env.DB,"last_full_step",iso());}
     catch(e){await putSetting(env.DB,"last_full_error",String(e.name||"Error"));if(e instanceof Restricted)return;console.warn("full scan failed",e.name);}
   }
   if(env.LIVE_MODE!=="true")return; // Discovery-only phase: never emit Telegram messages.
   if(env.WEBHOOK_ENABLED==="true"){
     if(!env.TELEGRAM_BOT_TOKEN||!env.TELEGRAM_CHAT_ID||!env.PUBLIC_WORKER_URL){
       console.warn("Activation blocked: missing Telegram secret, owner chat, or canonical URL");return;
     }
     if(!(await settings(env.DB,"webhook_installed_at"))){
       const u=new URL(env.PUBLIC_WORKER_URL);
       if(u.protocol!=="https:"||!u.hostname.endsWith(".workers.dev"))throw new Error("Invalid worker URL");
       await tg(env,"setWebhook",{url:u.origin+"/telegram/webhook",secret_token:await webhookSecret(env),allowed_updates:["message","callback_query"],max_connections:1,drop_pending_updates:false});
       await putSetting(env.DB,"webhook_installed_at",iso());
     }
   }
   if(minute%2===0){try{await statusWatch(env,c);}catch(e){if(e instanceof Restricted)return;console.warn("status failed",e.name);}}
   try{await deliver(env,c);}catch(e){if(e instanceof Restricted)return;console.warn("delivery failed",e.name);}
   if(vilniusMinute()>=8*60+30&&vilniusMinute()<9*60){
     const mark=await env.DB.prepare("INSERT OR IGNORE INTO daily_reports(local_day,state) VALUES(?,'sending')").bind(c.today).run();
     if(mark.meta.changes){try{await tg(env,"sendMessage",{chat_id:env.TELEGRAM_CHAT_ID,text:await reportText(env,"report",c),parse_mode:"HTML"});await env.DB.prepare("UPDATE daily_reports SET state='sent' WHERE local_day=?").bind(c.today).run();}catch(e){await env.DB.prepare("UPDATE daily_reports SET state='uncertain' WHERE local_day=?").bind(c.today).run();}}
   }
 }finally{await release(env,"cron");}
}
export const __test={petTier,journey,windowFor,suitable,urgent,shouldAlert,priority,fingerprint,searchRows,buttons,caption,vilniusDay};
export default {
 async fetch(request,env){
   const url=new URL(request.url);
   if(url.pathname==="/health"&&request.method==="GET")return Response.json({service:"ths-cloudflare-staging",stage:env.LIVE_MODE!=="true",ready:!!env.DB,send_enabled:env.LIVE_MODE==="true",scan_enabled:env.SCAN_ENABLED==="true"});
   if(url.pathname!=="/telegram/webhook"||request.method!=="POST")return new Response("Not found",{status:404});
   if(env.LIVE_MODE!=="true"||env.WEBHOOK_ENABLED!=="true")return new Response("Webhook disabled on staging",{status:409});
   if(!env.TELEGRAM_BOT_TOKEN||request.headers.get("X-Telegram-Bot-Api-Secret-Token")!==await webhookSecret(env))return new Response("Forbidden",{status:403});
   if(!env.DB||!env.TELEGRAM_CHAT_ID||!env.TELEGRAM_BOT_TOKEN)return new Response("Unconfigured",{status:503});
   let body;try{body=await request.json();}catch{return new Response("Bad JSON",{status:400});}
   try{await telegramUpdate(env,body);return new Response("OK");}catch(e){console.warn("webhook failure",e.name);return new Response("Handler failed",{status:503});}
 },
 async scheduled(controller,env,ctx){ctx.waitUntil(scheduler(env,controller));}
};
