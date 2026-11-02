import {test} from "node:test";
import assert from "node:assert/strict";
import {__test as t} from "../src/index.js";
test("Sittify forwarding address matches but other sources do not",()=>{
 assert.equal(t.notificationSource("forward@gmail.com","Sittify <news@sittify.com>"),"sittify");
 assert.equal(t.notificationSource("announcements@sittify.com","announcements@sittify.com"),"sittify");
 assert.equal(t.notificationSource("spam@example.org","spam@example.org"),null);
 assert.equal(t.mailboxDomain("User <FOO@EXAMPLE.ORG>"),"example.org");
});
test("safe notification link extraction includes only approved HTTPS hosts",()=>{
 const links=t.alertLinks("Alert https://sittify.com/sit/123?x=1&amp;y=2 and https://www.trustedhousesitters.com/house-and-pet-sitting-assignments/l/123/ https://bad.example/xxx");
 assert.equal(links.length,2);
 assert.equal(links[0],"https://sittify.com/sit/123?x=1&y=2");
 assert.equal(links[1],"https://www.trustedhousesitters.com/house-and-pet-sitting-assignments/l/123/");
 assert.deepEqual(t.alertLinks("http://sittify.com/ & https://evil.com"),[]);
});
