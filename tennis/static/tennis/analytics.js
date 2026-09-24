(function () {
  "use strict";
  const el = document.getElementById("analytics-config");
  if (!el || navigator.globalPrivacyControl === true || navigator.doNotTrack === "1") return;
  const config = JSON.parse(el.textContent);
  const frame = document.createElement("iframe");
  frame.hidden = true;
  frame.title = "利用状況の計測";
  frame.referrerPolicy = "no-referrer";
  frame.src = "/analytics/frame/";
  let ready = false;
  const pending = [];
  function send(event) {
    const data = Object.assign({}, event, {type: "deucenet-analytics"});
    if (ready) frame.contentWindow.postMessage(data, window.location.origin);
    else pending.push(data);
  }
  window.addEventListener("message", function (event) {
    if (event.origin !== window.location.origin || event.source !== frame.contentWindow || event.data?.type !== "deucenet-analytics-ready") return;
    if (ready) return;
    ready = true;
    pending.splice(0).forEach(data => frame.contentWindow.postMessage(data, window.location.origin));
  });
  if (config.page) send({name: "page_view", page: config.page, referrer: config.referrer});
  config.events.forEach(send);
  let started = false;
  document.addEventListener("deucenet:registration-start", function () {
    if (!started) { started = true; send({name: "registration_start"}); }
  });
  document.body.appendChild(frame);
}());
