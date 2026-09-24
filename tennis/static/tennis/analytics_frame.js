/* GA runs only inside this fixed, empty document, never inside a token URL. */
(function () {
  "use strict";
  if (window.parent === window) return;
  const origin = window.location.origin;
  const id = document.body.dataset.measurementId;
  const pages = new Set(["/", "/guide/", "/privacy/", "/terms/"]);
  const paths = {
    demo_start: "/demo", registration_start: "/", registration_email_sent: "/",
    sign_up: "/registration/complete/", first_event_created: "/registration/first-event/"
  };
  const titles = {"/": "DeuceNet", "/guide/": "利用案内 | DeuceNet", "/privacy/": "プライバシーポリシー | DeuceNet", "/terms/": "利用規約 | DeuceNet"};
  window.dataLayer = window.dataLayer || [];
  function gtag() { window.dataLayer.push(arguments); }
  gtag("js", new Date());
  gtag("config", id, {
    send_page_view: false, page_location: "https://deucenet.app/", page_referrer: "",
    page_title: "DeuceNet", allow_google_signals: false, allow_ad_personalization_signals: false
  });
  const script = document.createElement("script");
  script.async = true;
  script.referrerPolicy = "no-referrer";
  script.src = "https://www.googletagmanager.com/gtag/js?id=" + encodeURIComponent(id);
  document.head.appendChild(script);
  window.addEventListener("message", function (event) {
    if (event.origin !== origin || event.source !== window.parent) return;
    const d = event.data;
    if (!d || d.type !== "deucenet-analytics") return;
    if (d.name === "page_view" ? !pages.has(d.page) : !Object.hasOwn(paths, d.name)) return;
    const params = {
      page_location: "https://deucenet.app" + (d.name === "page_view" ? d.page : paths[d.name]),
      page_title: d.name === "page_view" ? titles[d.page] : "DeuceNet",
      page_referrer: ""
    };
    if (/^https:\/\/(google\.com|google\.co\.jp|bing\.com|yahoo\.co\.jp|chatgpt\.com|perplexity\.ai|t\.co|x\.com)\/$/.test(d.referrer || "")) params.page_referrer = d.referrer;
    if (d.mode === "admin" || d.mode === "member") params.demo_mode = d.mode;
    if (d.name === "sign_up") params.method = "email";
    if (d.client_id && /^\d+\.\d+$/.test(d.client_id)) params.client_id = d.client_id;
    gtag("event", d.name, params);
  });
  window.parent.postMessage({type: "deucenet-analytics-ready"}, origin);
}());
