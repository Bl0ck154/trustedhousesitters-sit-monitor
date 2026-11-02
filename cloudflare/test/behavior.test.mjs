import {test} from "node:test";
import assert from "node:assert/strict";
import worker,{__test as t} from "../src/index.js";

const start="2026-10-26", today="2026-10-17";
const booked=[{assignment_id:"1",start:"2026-10-27",end:"2026-11-14",country:"Germany"}];
const sit=(pets={cat:1},startDate="2026-11-14",endDate="2026-11-25")=>({
 assignment_id:"1234",listing_id:"12",status:"open",pets,start:startDate,end:endDate,
 country:"Germany",transit_warning:false,internet:"basic",verified_by_detail:true,
 photo_urls:["https://res.cloudinary.com/trustedhousesitters/image/upload/example.jpg"],pet_photo_urls:[]
});

test("booked dates are half-open and next focus is Nov 14",()=>{
 const j=t.journey(booked,start,today);
 assert.deepEqual(j.focus[0],"2026-11-14");
 assert.deepEqual(j.bridges,[["2026-10-26","2026-10-27"]]);
});
test("no recommendations overlapping confirmed nights",()=>{
 assert.equal(t.suitable(sit({cat:1},"2026-11-13","2026-11-24"),booked,start,today),false);
 assert.equal(t.suitable(sit(),booked,start,today),true);
});
test("tiers and dog-urgency policy mirror Python logic",()=>{
 assert.equal(t.petTier(sit({cat:1})),"A");
 assert.equal(t.petTier(sit({dog:2})),"B");
 assert.equal(t.petTier(sit({dog:3})),"C");
 assert.equal(t.petTier(sit({horse:1})),"C");
 assert.equal(t.shouldAlert(sit({dog:1}),booked,start,today),false);
 assert.equal(t.shouldAlert(sit({cat:1}),booked,start,today),true);
 assert.equal(t.shouldAlert(sit({dog:1}),booked,start,"2026-11-06"),true);
});
test("public canApply is not personal confirmation",()=>{
 const listing={id:12,title:"Cats",animals:[{slug:"cat",count:1}],location:{countryName:"Germany",name:"Berlin"},
 publishedAssignment:[{id:1234,startDate:"2026-11-14",endDate:"2026-11-25",applicationsCount:3,canApply:true}]};
 const state={search:{listings:{"search-listings-results":{total:1,results:[12]}},listing:{"12":listing}}};
 const c={window:["2026-11-14","2026-12-14"]};
 const x=t.searchRows(state,c);
 assert.equal(x.rows.length,1);
 assert.equal(x.rows[0].status,"open");
 assert.equal(x.rows[0].application_count,3);
 assert.equal(x.rows[0].verified_by_detail,false);
});
test("photo card inline controls include independent home/pet galleries and explicit confirmation",()=>{
 const i={...sit(),pet_photo_urls:["https://res.cloudinary.com/trustedhousesitters/image/upload/pet.jpg"]};
 const rows=t.buttons(i,true,false).inline_keyboard;
 const actions=rows.flatMap(x=>x.map(y=>y.callback_data));
 assert.ok(actions.includes("t3:g:1234"));
 assert.ok(actions.includes("t3:t:1234"));
 assert.ok(actions.includes("t3:k:1234"));
 assert.ok(actions.includes("t3:u:1234"));
 assert.ok(actions.includes("t3:i:1234:1"));
});
test("staging health is harmless and webhook always disabled",async()=>{
 const env={LIVE_MODE:"false",SCAN_ENABLED:"false",WEBHOOK_ENABLED:"false",DB:{}};
 const health=await worker.fetch(new Request("https://example.com/health"),env);
 assert.equal(health.status,200);
 const payload=await health.json();
 assert.equal(payload.send_enabled,false);
 assert.equal(payload.scan_enabled,false);
 const hook=await worker.fetch(new Request("https://example.com/telegram/webhook",{method:"POST"}),env);
 assert.equal(hook.status,409);
});
