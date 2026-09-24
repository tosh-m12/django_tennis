# DeuceNet GA4

- Account: BL101 / 80828270
- Property: DeuceNet / 555625786
- Web stream: DeuceNet Web / 15834412178
- Measurement ID: G-F55BNG3CBE (public identifier, not a secret)
- Time zone / currency: Japan / JPY
- Enhanced measurement: OFF. Keep it off; form and link auto-collection is unnecessary.
- Dashboard: https://analytics.google.com/analytics/web/#/a80828270p555625786/reports/intelligenthome

## Events

| Event | Meaning |
|---|---|
| page_view | Public home, guide, privacy or terms view; use users/sessions for visitors, not event totals |
| demo_start | Demo successfully created/reused and destination rendered; demo_mode=member/admin; repeat entry in the same mode within 30 minutes is suppressed |
| registration_start | Valid club name entered and registration modal opened; once per page load |
| registration_email_sent | New club saved and confirmation email send accepted; once per successful submission |
| sign_up | Initial registrant's email confirmed; once per new club, independent of repeat links or email changes |
| first_event_created | First practice event created for a club registered after measurement launch; once per club, demo excluded |

The demo is optional: analyze direct registration and registration via demo separately. Use GA4 Events / Explore for counts and visitor-based funnels. Key event: sign_up. Register demo_mode as an event-scoped custom dimension.

## Data boundaries

Third-party JavaScript loads only in a fixed `/analytics/frame/` document. The parent app passes allowlisted events using same-origin postMessage. The relay constructs fixed public/virtual URLs and titles, never arbitrary page URLs, queries, names, email addresses or club IDs/tokens. The iframe has no-referrer policy, is not indexed and is same-origin frameable only. Referrers are reduced to a short allowlist of search/AI/social domains; other sources are not classified. UTM parameters are intentionally not collected in this first release.

GA4 client ID from the first-party `_ga` cookie is captured at new registration and supplied for confirmation/activation events, allowing the original browser to be associated when the confirmation opens on another device. No user ID is set. Without the original cookie, cross-device attribution is unavailable. Only anonymous client ID and one-off conversion timestamps are added to the registration record.

Ad blockers, disabled JavaScript, GPC/DNT, early tab closure and network errors can prevent browser delivery. DB markers prevent repeated conversion links from inflating counts; they are not a guaranteed-delivery queue. GA4 is for trends, not billing or an exact database census. Demo cleanup does not erase events already received by GA4. Historical visits cannot be backfilled.

## Operations

`GA4_MEASUREMENT_ID` can be overridden (empty disables delivery). Production host is explicitly allowlisted; local and CI runs do not send GA4 events. Migration 0030 is required before running the new release. Tests cover repeats, invalid verification, changed emails, separate browsers, demo roles, first event and payload filtering. Use the realtime report after deploy to verify actual receipt; normal reports take longer to populate.
