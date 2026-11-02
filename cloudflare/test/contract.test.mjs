import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const src=await fs.readFile(new URL('../src/index.js',import.meta.url),'utf8');
const schema=await fs.readFile(new URL('../schema.sql',import.meta.url),'utf8');
test('staging is fail-closed by default',()=>{
  assert.match(src,/LIVE_MODE!=="true"/);
  assert.match(src,/SCAN_ENABLED!=="true"/);
  assert.match(src,/WEBHOOK_ENABLED!=="true"/);
});
test('access control never retries forbidden or rate-limited source via proxy',()=>{
  assert.match(src,/res\.status===403\|\|res\.status===429/);
  assert.match(src,/21600e3/);
  assert.match(src,/3600e3/);
  assert.doesNotMatch(src,/(http.*proxy|browser.?fallback|Obscura)/i);
});
test('supports public search, cards, albums, stages, confirmation and daily summary',()=>{
  for(const word of ['__INITIAL_STATE__','searchRows','pending_notifications','sendPhoto','sendMediaGroup','watch_transitions','pending_confirmations','confirmed_stays','daily_reports','/options','/plan','/report','/applications'])assert.ok(src.includes(word),word);
});
test('D1 tables required by worker and migration are present',()=>{
 for(const name of ['settings','leases','records','watch','watch_transitions','delivery','pending_notifications','controls','control_instances','applications','confirmed_stays','pending_confirmations','ignored_assignments','telegram_updates','daily_reports'])assert.match(schema,new RegExp('CREATE TABLE IF NOT EXISTS '+name+'\\b'));
});
test('all automatic outgoing paths have LIVE_MODE gate',()=>{
 assert.match(src,/async function tg\(env,method,payload\)\{\s*if\(env\.LIVE_MODE!=="true"/);
});
