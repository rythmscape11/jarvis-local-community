const http = require('node:http');
function cookieValue(headers) {
  const list = headers['set-cookie'];
  if (!Array.isArray(list)) throw new Error('Local session cookie missing');
  const cookie = list.map((line) => /^jarvis_session=([A-Za-z0-9_-]{40,100});/.exec(line)).find(Boolean);
  if (!cookie) throw new Error('Invalid local session cookie');
  return cookie[1];
}
function authenticate(token, origin) {
  const url = new URL(origin);
  if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1') throw new Error('Session must use loopback');
  return new Promise((resolve,reject) => {
    const body = JSON.stringify({token});
    const request = http.request(origin+'/api/session',{method:'POST',timeout:5000,headers:{Origin:origin,'Content-Type':'application/json','Content-Length':Buffer.byteLength(body)}},(response) => {
      response.resume();
      if (response.statusCode !== 200) return reject(new Error('Local session authentication failed'));
      try { resolve(cookieValue(response.headers)); } catch (error) { reject(error); }
    });
    request.on('error', () => reject(new Error('Local authentication service unavailable')));
    request.on('timeout', () => { request.destroy(); reject(new Error('Local session timed out')); });
    request.end(body);
  });
}
module.exports = {cookieValue,authenticate};
