const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../static/tennis/analytics_frame.js'), 'utf8');
function harness() {
  let listener;
  const parent = {postMessage() {}};
  const window = {parent, location: {origin: 'https://deucenet.app'}, addEventListener(n, fn) {listener = fn;}};
  const document = {body: {dataset: {measurementId: 'G-TEST'}}, createElement() {return {};}, head: {appendChild() {}}};
  vm.runInNewContext(source, {window, document});
  const send = data => listener({origin: window.location.origin, source: parent, data: {type: 'deucenet-analytics', ...data}});
  return {window, parent, listener, send};
}
test('only fixed fields reach GA; token URLs and form values cannot be forwarded', () => {
  const h = harness();
  h.send({name: 'sign_up', page: '/c/secret/', email: 'private@example.com', page_title: 'private name', referrer: 'https://example.com/secret', client_id: '123.456'});
  const commands = h.window.dataLayer.map(x => Array.from(x));
  const event = commands.at(-1);
  assert.equal(event[1], 'sign_up');
  assert.equal(event[2].page_location, 'https://deucenet.app/registration/complete/');
  assert.equal(event[2].client_id, '123.456');
  assert.equal(event[2].method, 'email');
  assert.ok(!JSON.stringify(commands).match(/secret|private/));
});
test('foreign messages, unknown events and private page views are rejected', () => {
  const h = harness();
  const initial = h.window.dataLayer.length;
  h.send({name: 'page_view', page: '/c/token/'});
  h.send({name: 'constructor'});
  h.send({name: 'unknown'});
  h.listener({origin: 'https://attacker.example', source: h.parent, data: {type: 'deucenet-analytics', name: 'sign_up'}});
  assert.equal(h.window.dataLayer.length, initial);
  h.send({name: 'demo_start', mode: 'admin'});
  assert.equal(h.window.dataLayer.at(-1)[2].demo_mode, 'admin');
});
