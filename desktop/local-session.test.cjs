const test = require('node:test');
const assert = require('node:assert/strict');
const {cookieValue,authenticate} = require('./local-session.cjs');
test('accepts only exact local session cookie, without exposing token in URLs', () => {
 const token='a'.repeat(43);
 assert.equal(cookieValue({'set-cookie':['jarvis_session='+token+'; HttpOnly; SameSite=strict']}),token);
 for (const headers of [{},{'set-cookie':['other='+token+';']},{'set-cookie':['jarvis_session=invalid;']}]) assert.throws(()=>cookieValue(headers));
 assert.throws(()=>authenticate('fixture','https://unrelated.example'));
});
