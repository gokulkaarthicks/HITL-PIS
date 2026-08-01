-- Human-in-the-Loop Prompt Improvement System -- seed data
--
-- Apply with:  psql "$SUPABASE_DB_URL" -f supabase/seed.sql
-- or paste into the Supabase SQL editor. Run schema.sql first.
--
-- Idempotent: bootstrap blocks skip populated tables, while the expanded
-- review pool checks reports individually. Re-running never duplicates or
-- deletes your work.
--
-- 111 bug reports total, split into two disjoint sets:
--   * 93 -> bug_reports         (the review pool the human corrects)
--   * 18 -> evaluation_examples (held-out gold set, never used as few-shot)
-- The split is deliberate: an improved prompt built from corrections must be
-- scored on text it has never seen, otherwise the accuracy gain is just recall.

-- ---------------------------------------------------------------------------
-- Baseline prompt (v1). Intentionally plain: it states the task and the output
-- contract but gives no severity calibration and no tie-breaking rules for
-- component. Those are exactly what human corrections will teach later.
-- ---------------------------------------------------------------------------
insert into prompt_versions
    (version_name, prompt_text, is_active, lifecycle_status,
     created_from_corrections_count)
values (
    'v1-baseline',
    'You are a bug report triage assistant. Read the bug report and classify it.

Return a JSON object with exactly these fields:
- "severity": one of "critical", "high", "medium", "low"
- "component": one of "frontend", "backend", "mobile", "auth", "payments", "database", "infrastructure", "unknown"
- "rationale": one or two sentences explaining the classification

Return only the JSON object and nothing else.',
    true,
    'active',
    0
)
on conflict (version_name) do nothing;

-- ---------------------------------------------------------------------------
-- Base review pool: 32 reports (source = seed, status = new)
-- ---------------------------------------------------------------------------
do $seed$
begin
if not exists (select 1 from bug_reports) then
    insert into bug_reports (report_text, source) values
    ('Payment capture fails with gateway error CARD_DECLINED for all Visa cards issued in the EU. Roughly 2,000 checkouts have failed since 09:00 UTC.', 'seed'),
    ('The password reset link expires after 30 seconds instead of the documented 24 hours, so nobody can complete a reset.', 'seed'),
    ('Primary Postgres replica has been lagging 45 minutes behind for the past two days. Reports built on the replica show stale numbers.', 'seed'),
    ('App crashes with a null pointer exception when a user opens the Profile tab without a saved avatar. Reproduced on Android 12 and 14.', 'seed'),
    ('The marketing site footer shows the wrong copyright year.', 'seed'),
    ('All background workers stopped consuming from the queue after the Kubernetes node pool was upgraded. Jobs are piling up.', 'seed'),
    ('Two-factor authentication codes are accepted up to 10 minutes after they expire, widening the window for replay attacks.', 'seed'),
    ('Search results page renders the loading skeleton indefinitely when the query returns zero results, instead of showing an empty state.', 'seed'),
    ('Subscription renewals are charging customers the old price after they downgrade their plan mid-cycle.', 'seed'),
    ('GET /v1/orders p99 latency rose from 300ms to 4.5s after the last deploy. No schema changes were involved.', 'seed'),
    ('Tooltip text on the billing page overflows its container at viewport widths below 360px.', 'seed'),
    ('A migration added a non-null column without a default to a 40 million row table and locked writes for 12 minutes during business hours.', 'seed'),
    ('iOS app does not refresh the feed when pulled down; the spinner appears but no network request is made.', 'seed'),
    ('User reports that something is broken on the dashboard. No screenshot, no browser, no steps to reproduce, and support cannot reproduce it.', 'seed'),
    ('Autoscaling group scaled to zero instances overnight because the health check path was changed without updating the target group.', 'seed'),
    ('Sorting the invoice table by amount sorts lexicographically, so 900 appears after 1000.', 'seed'),
    ('Logging out on one device does not revoke the refresh token on other devices. Stolen tokens remain usable.', 'seed'),
    ('The onboarding checklist shows a progress bar at 90% even after every step is completed.', 'seed'),
    ('Webhook deliveries to merchant endpoints are retried without an idempotency key, so merchants record duplicate payments.', 'seed'),
    ('Redis cache eviction policy is set to noeviction, so the cache fills up and every write starts erroring under load.', 'seed'),
    ('Push notification deep links open the app home screen rather than the referenced conversation on Android.', 'seed'),
    ('The date picker allows selecting a return date earlier than the departure date and the form submits without validation error.', 'seed'),
    ('Signup allows an email address that is already registered when the address differs only by letter case, creating duplicate accounts.', 'seed'),
    ('Nightly backup job reports success but the resulting dump file is zero bytes. This has been the case for six nights.', 'seed'),
    ('Currency amounts are rendered without thousand separators in the German locale.', 'seed'),
    ('The API returns 200 with an empty body instead of 404 when a resource does not exist, so clients cannot distinguish the cases.', 'seed'),
    ('Mobile app uploads photos at full resolution over cellular, consuming several hundred megabytes per session.', 'seed'),
    ('Admin users can view any customer invoice by changing the id in the URL; there is no ownership check on the endpoint.', 'seed'),
    ('CDN is serving a stale JavaScript bundle to about 15% of users because cache headers were set to one year with no content hash.', 'seed'),
    ('The contact form submit button stays disabled after a failed submission, so the user cannot retry without reloading.', 'seed'),
    ('Refund webhooks from the payment provider are processed out of order, occasionally marking a refunded order as paid again.', 'seed'),
    ('Someone mentioned the reports look off this week. No specifics were provided and no report was named.', 'seed');
end if;
end
$seed$;

-- ---------------------------------------------------------------------------
-- Expanded review pool: 61 additional reports (93 review reports total)
--
-- Unlike the original bootstrap guard above, this insert checks each report.
-- Re-running seed.sql therefore upgrades an existing 32-report database while
-- remaining safe to run repeatedly without duplicating seeded reports.
-- ---------------------------------------------------------------------------
insert into bug_reports (report_text, source)
select seeded.report_text, 'seed'
from (values
    ('The account settings modal closes without saving when the user presses Enter in the display-name field.'),
    ('Keyboard focus becomes trapped inside the cookie banner, preventing keyboard users from reaching the page content.'),
    ('The analytics chart legend uses the same color for active and cancelled subscriptions.'),
    ('Product images stretch vertically on tablet screens when the source image has a portrait aspect ratio.'),
    ('The dashboard flashes protected account data for a moment before redirecting an expired session to login.'),
    ('Copying a multiline API key from the credentials page removes newline characters from the clipboard value.'),
    ('The notification menu is positioned outside the viewport when opened from a right-to-left locale.'),
    ('Submitting the profile form twice quickly creates duplicate success banners that cannot be dismissed.'),
    ('The accessibility label for the delete-project button reads edit project in screen readers.'),
    ('A 25-megabyte source map is included in the public production JavaScript bundle, slowing the first page load.'),
    ('The bulk user import endpoint returns success after processing only the first 1,000 rows of larger CSV files.'),
    ('Concurrent updates to the same support ticket overwrite the earlier agent response without a conflict warning.'),
    ('The order API accepts a negative quantity and creates a credit instead of rejecting the request.'),
    ('A malformed filter parameter causes the search endpoint to expose an internal stack trace in its response.'),
    ('Scheduled reports run twice after daylight-saving time changes, sending duplicate emails to every recipient.'),
    ('The GraphQL resolver loads account permissions once per project, causing more than 500 database queries on the portfolio page.'),
    ('Deleting a team returns before its asynchronous cleanup is scheduled, leaving orphaned files indefinitely.'),
    ('The audit-log endpoint skips events created during the same millisecond because pagination uses a timestamp-only cursor.'),
    ('A cancelled document export continues consuming CPU for several hours after the client disconnects.'),
    ('The inventory reservation API sometimes returns HTTP 200 before the reservation transaction commits.'),
    ('The Android app loses unsent chat messages whenever the device rotates from portrait to landscape.'),
    ('Voice messages recorded on iOS play back at double speed after the application resumes from the background.'),
    ('Biometric unlock enters an endless spinner after the user adds a new fingerprint in device settings.'),
    ('The mobile app displays cached account details from the previous user after logout and login on a shared device.'),
    ('Android push notifications create a new conversation screen instead of opening the existing screen in the navigation stack.'),
    ('Offline edits are uploaded in reverse order when connectivity returns, restoring an older document version.'),
    ('The iOS share sheet crashes when sharing a filename that contains an emoji.'),
    ('Location permission is requested on every launch even after the user permanently denies it.'),
    ('Passwordless login links can be used more than once before they expire.'),
    ('Changing an account email address does not require reauthentication or confirmation from the old address.'),
    ('The login rate limiter keys requests only by IP address, allowing one office user to lock out everyone behind the same proxy.'),
    ('Invitations to a private workspace remain valid after an administrator revokes them.'),
    ('The SAML callback accepts an assertion whose audience belongs to a different tenant.'),
    ('Users with a disabled account can still exchange an existing refresh token for new access tokens.'),
    ('Recovery codes are displayed again in account settings without requiring the user to enter a password.'),
    ('The remember-me option is ignored and all web sessions expire after one hour.'),
    ('A failed card authorization is recorded as a completed charge when the provider response arrives after the request timeout.'),
    ('Customers are charged sales tax twice when a discount code reduces the order total to less than one dollar.'),
    ('The billing portal allows a user to download an invoice belonging to another organization by changing its identifier.'),
    ('Payout reconciliation rounds each transaction before summing, producing a growing mismatch with the payment provider balance.'),
    ('A subscription remains active after the final retry for its payment fails and the grace period expires.'),
    ('The checkout page applies a gift card balance but also charges the full amount to the customer card.'),
    ('Refund status webhooks are ignored when the provider sends uppercase event names.'),
    ('Invoices generated in Japanese yen incorrectly include two decimal places and charge the rounded value.'),
    ('The customer table scan for weekly billing blocks order writes for several minutes every Monday morning.'),
    ('Deleting a parent record leaves millions of child rows because the cleanup worker uses the wrong foreign-key column.'),
    ('The read replica serves records that were deleted more than an hour ago even though replication lag reports zero seconds.'),
    ('A connection leak in the reporting service exhausts the database pool after approximately 10,000 exports.'),
    ('Database timestamps written during the daylight-saving transition are shifted forward by one hour.'),
    ('The uniqueness constraint on usernames is missing, allowing duplicate usernames during concurrent signups.'),
    ('Restoring the latest backup fails because one encrypted archive segment is missing from object storage.'),
    ('The production container restarts continuously because its memory limit is lower than the application startup requirement.'),
    ('DNS failover still points traffic to the unhealthy primary region ten minutes after the health check fails.'),
    ('Log rotation is disabled on API nodes, filling the root filesystem and preventing new deployments.'),
    ('The message queue dead-letter policy immediately redrives poison messages, creating an infinite processing loop.'),
    ('A firewall rule exposes the internal metrics dashboard to the public internet without authentication.'),
    ('The deployment pipeline reports success even when the database migration job exits with a failure code.'),
    ('Object-storage lifecycle rules delete customer exports after one day instead of the configured thirty days.'),
    ('A customer says notifications are bad lately but does not identify the channel, device, account, or expected behavior.'),
    ('Support reports intermittent slowness somewhere in the product, with no timestamps, affected pages, or reproduction steps.'),
    ('The weekly numbers appear incorrect according to one user, but the report does not name a dashboard or provide expected values.')
) as seeded(report_text)
where not exists (
    select 1
    from bug_reports existing
    where existing.report_text = seeded.report_text
);

-- ---------------------------------------------------------------------------
-- Held-out gold set: 18 examples with expected labels
-- ---------------------------------------------------------------------------
do $seed$
begin
if not exists (select 1 from evaluation_examples) then
    insert into evaluation_examples
        (report_text, expected_severity, expected_component, expected_rationale) values
    ('Checkout returns HTTP 500 for every customer attempting to pay with a saved card. No orders have completed in the last 40 minutes.',
     'critical', 'payments',
     'Total revenue outage affecting all customers with no workaround.'),
    ('The "Forgot password" email never arrives for accounts registered with a Yahoo address, so those users cannot regain access.',
     'high', 'auth',
     'Account recovery is blocked for a identifiable subset of users.'),
    ('The button label on the settings page is misaligned by about 3 pixels in Safari.',
     'low', 'frontend',
     'Cosmetic rendering issue with no functional impact.'),
    ('The nightly ETL job silently drops rows when the source CSV contains a UTF-8 byte order mark, corrupting the reporting tables.',
     'high', 'database',
     'Silent data corruption in stored reporting data.'),
    ('The entire API is unreachable; the load balancer health check is failing across all three regions.',
     'critical', 'infrastructure',
     'Full platform outage at the load balancing layer.'),
    ('On Android 13 the app crashes immediately on launch after the 4.2.1 update.',
     'critical', 'mobile',
     'App is completely unusable for an entire OS version.'),
    ('Session tokens are not invalidated after a user changes their password; old sessions stay valid indefinitely.',
     'high', 'auth',
     'Security defect that leaves compromised sessions active.'),
    ('The dark mode toggle resets to light after a full page reload.',
     'low', 'frontend',
     'Minor preference persistence issue with an easy workaround.'),
    ('Refunds issued through the admin panel are recorded twice, so customers receive double the refund amount.',
     'critical', 'payments',
     'Direct and ongoing financial loss on every refund.'),
    ('The /v1/search endpoint takes 8 to 12 seconds under normal load; it previously returned in under 400ms.',
     'high', 'backend',
     'Severe performance regression on a core endpoint.'),
    ('Typo in the onboarding tooltip: "Recieve updates" should read "Receive updates".',
     'low', 'frontend',
     'Copy error with no functional impact.'),
    ('The database connection pool exhausts every day around 2pm, causing intermittent 503s until someone restarts the service manually.',
     'high', 'database',
     'Recurring daily outage requiring manual intervention.'),
    ('Push notifications on iOS arrive up to 6 hours late.',
     'medium', 'mobile',
     'Feature works but is degraded enough to lose most of its value.'),
    ('Users report the app feels weird since yesterday. No further detail was provided and the team cannot reproduce it.',
     'low', 'unknown',
     'Not reproducible and no component can be identified from the report.'),
    ('The TLS certificate for api.example.com expires in 3 days and auto-renewal has been failing silently.',
     'high', 'infrastructure',
     'Imminent full outage that is still preventable.'),
    ('Pagination on the orders list returns duplicate records between page 2 and page 3.',
     'medium', 'backend',
     'Incorrect results from the API with a partial workaround.'),
    ('OAuth login with Google succeeds but redirects to a blank page instead of the dashboard.',
     'high', 'auth',
     'Login path is broken for users who rely on Google sign-in.'),
    ('The CSV export downloads the correct rows but the column headers are missing from the file.',
     'low', 'frontend',
     'Output is usable and the defect is cosmetic.');
end if;
end
$seed$;
