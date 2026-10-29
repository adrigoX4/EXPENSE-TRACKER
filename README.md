# College Cart Personal Manager

A local-first manager for a college snack cart: record sales even when the College Cart website or internet is down, track stock, cash, expenses, money received and given, customer balances, deliveries and backups.

The app runs on your own computer at `http://127.0.0.1:8000` with a SQLite database and an installable PWA frontend. No customer data is sent to a third party.

> **College Cart website integration:** there is no automated import or sync with the public College Cart website. No authorized API is available to this app. You can optionally paste a website order ID when recording a sale; the app stores it, warns about duplicate IDs and lets you verify it manually from the sale detail screen.

---

## Quick start (Windows)

Run from the project folder (`C:\Users\adars\OneDrive\Desktop\CartFlow`):

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m app.bootstrap --seed
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Git Bash equivalent:

```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
python -m app.bootstrap --seed
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. On the first visit you are asked to **create an account**. That first account keeps any records already in `college_cart.db`; every later account gets its own separate database. API docs are at <http://127.0.0.1:8000/api/docs>, health check at `/api/health`.

`python -m app.bootstrap --seed` creates or upgrades the schema with Alembic and adds **four clearly fictional demo products**. It never seeds sales, payments, expenses or any financial transaction. The seed is skipped if products already exist.

### Upgrading an existing database

Stop the server, then run:

```bash
python -m app.bootstrap
```

This applies pending Alembic migrations without deleting data. Back up first if the records matter.

### Empty database without demo products

Stop the server first. To remove the business records but keep accounts, delete the business database files:

```bash
rm college_cart.db college_cart.db-wal college_cart.db-shm
rm -rf user_data
python -m app.bootstrap
```

The next sign-in recreates an empty schema for that account. To remove accounts and every user entirely, also delete `accounts.db` (and its `-wal`/`-shm` files); the next visit starts the first-account signup again.

This permanently deletes local data. Create and download a backup first if you need the existing records. Starting empty is fully supported: add products from Inventory, then record sales.

### Accounts and data layout

- `accounts.db` holds only account records: email, password hash, data-file location, owner flag and login timestamps. It never holds sales or money data.
- The first account created points at the existing `college_cart.db`. Every later account gets its own file under `user_data/user-<id>.db`.
- Sessions use a signed, HttpOnly, SameSite=Lax cookie. Passwords are stored as PBKDF2-HMAC-SHA256 hashes with per-user salts and 600,000 iterations.
- Sign up and sign in at `/signup` and `/login`; the sidebar shows the signed-in email and a **Sign out** button.
- Set `CARTFLOW_ALLOW_SIGNUP=false` after creating your accounts to close public registration.
- Each account can create, download and restore only its own backup. Offline queues are also namespaced per account in the browser.

### Tests

```bash
python -m pytest -q
```

Current result: **72 passed** (one third-party Starlette/httpx deprecation warning). Tests use isolated temporary SQLite databases and never touch `college_cart.db` or `accounts.db`.

| Test file | Covers |
| --- | --- |
| `tests/test_sales.py` | Sale creation, totals, discounts, idempotency, duplicate website order IDs, cancellation, audit trail |
| `tests/test_inventory.py` | Receipts, weighted-average cost, stock movements, returns, negative-stock rules |
| `tests/test_finance.py` | Cash/UPI payments, partial payments, refunds, expenses, ordinary vs stock spending, cash and balance summaries |
| `tests/test_money.py` | Money in/out, cash/UPI separation, backdated entries, filtering, running balances, corrections, voids, handovers, cash-to-UPI movements, linkage and duplicate prevention |
| `tests/test_reconciliation.py` | Website verification statuses, duplicate candidates, review decisions, manual verification |
| `tests/test_reports_backup.py` | Daily/monthly reports, CSV safety, exports, backup validation and guarded restore |
| `tests/test_offline_pwa.py` | Service worker shell, manifest, offline queue assets and replay-safe money entries |
| `tests/test_auth.py` | First account claims existing records, later-account isolation, duplicate email, password rules, login/logout, hashed passwords, tampered cookies, rate limits, CSRF, per-account backups and closed signup |
| `tests/test_seo_routes.py` | Clean URLs, per-page titles/descriptions/canonicals, sale-detail metadata, breadcrumb and LocalBusiness schema, custom 404, sitemap/robots/llms, indexing gate, favicon and share image, no source maps or Vite/React leftovers |

---

## Screens

The navigation has exactly these eight screens, plus a sale detail view and the sign-in/sign-up pages:

1. **Dashboard**
2. **New Sale**
3. **Sales History**
4. **Inventory**
5. **Expenses**
6. **Money History**
7. **Reports**
8. **Settings & Backup**

Desktop uses a sidebar. Mobile uses a bottom navigation bar with a **More** sheet. Pages are responsive at 390px and 1440px.

### Dashboard

- Exactly four metric cards:
  - **Today's sales** — net of returns.
  - **Money received** — sale payments plus unrelated incoming transfers, shown separately so they are never confused.
  - **Today's expenses** — ordinary operating expenses only; stock purchases are shown separately in the card note.
  - **Cash available** — physical cash only, with UPI shown separately.
- Quick actions: **New Sale**, **Add Expense**, **Add Transaction**, **Add Stock**.
- Five recent activities.
- Recent money in and out, pending customer payments, low-stock products and offline/sync status.
- Date filters: Today, Yesterday, Last 7 Days, This Month and Custom.
- No gross-profit, net-profit, margin, COGS or stock-valuation cards.

---

## New Sale

- Search products by name or SKU, filter by category, and see price and available stock.
- Quantity controls, discount and live totals.
- Stock is validated before saving; negative stock requires explicit confirmation and a reason.
- Price and cost snapshots are frozen on each sale line.
- Source: `manual`, `website` or `imported`.
- Optional customer name, phone and room reference; notes.
- Optional delivery status and delivery person.
- Optional website order ID. Before saving, the app checks for an existing sale with that ID and blocks a duplicate with a link to the existing sale.
- Payment can be full, partial or unpaid. Cash, UPI and other configured methods; up to five payment lines per sale. The app never assumes full payment.
- Sales can be cancelled from sale detail with a reason, or returned partially/full through the returns flow.
- Offline sales are queued with a **pending** marker and a clear confirmation containing a local reference and a link to Sales History. Pending sales are never shown as server-confirmed.

---

## Sales History and sale detail

- Search by sale number, customer, product or website order ID.
- Filter by date range, product, source, payment status and delivery status.
- Each row shows sale ID, date/time, product summary, total, received, outstanding, payment-method summary, source and sync status. Mobile rows include the same key information.
- Pagination for long lists.
- Sale detail shows items and quantities, frozen prices, payment history, returns, audit/correction history, notes, delivery status and website verification.
- Add a later payment with its actual time and method; the outstanding balance updates and the payment appears in Money History.
- Partial or full return with items, quantity, refund amount, refund method, restock option and reason.
- Cancellation preserves the record and audit trail. Financial records are never silently deleted.

### Website verification and duplicates

- Website verification statuses are edited manually: `recorded`, `verified`, `not found`, `potential duplicate`, `needs review`.
- The app never claims to read the College Cart website automatically.
- Similar sales on the same business day are surfaced as potential duplicates. Both records are always kept; review actions are **Keep both** or **Confirm duplicate**, stored for history.

---

## Inventory

- Product fields: name, optional SKU, category, purchase cost, selling price, stock, low-stock threshold, optional expiry date and active/inactive.
- Add and edit products, receive stock, correct stock with a reason, record damage/loss, and restock returns.
- Stock status labels: **In Stock**, **Low Stock**, **Out of Stock**.
- Movement history for `opening`, `receipt`, `sale`, `return`, `damage` and `correction`.
- Stock updates automatically when a sale syncs or a return is restocked.
- Negative stock is blocked by default with an explicit override and a reason.
- Receiving stock creates a linked **stock purchase** expense. That expense is shown separately from ordinary expenses and cannot be edited or voided independently, preventing double counting.
- Weighted-average purchase cost is used internally for snapshots; there is no stock-valuation dashboard.

---

## Expenses

- Fields: date and exact time, amount, category, method, paid to, description, reference/receipt number and note.
- Default categories can be edited in Settings: Travel, Food & refreshments, Packaging, Personal / other, Miscellaneous, plus reserved **Stock purchase**.
- Add, edit, view details and void with a retained history.
- Search and filter by search text, exact date range, category, method and voided status; quick ranges for Today, Yesterday, 7 days, This month and All time.
- Daily/monthly totals and category mix.
- CSV export with UTF-8 BOM and spreadsheet-formula protection.
- Cash expenses reduce physical cash; UPI expenses do not.
- **Ordinary expense** and **Stock purchase** are clearly distinguished. Stock purchases are created from Inventory → Receive stock and stay linked to the receipt. The Add Expense form does not offer the stock category, and the API rejects manual stock-purchase expenses so they cannot be double entered.

---

## Money History

Money History is the permanent, searchable ledger of money given and received.

Each entry shows date/time, person/party, reason/category, direction, amount, method, related sale/expense/receipt and running cash/UPI balance. Incoming amounts are green, outgoing amounts red. Records are ordered newest first with a stable tie-breaker.

### Manual Add Transaction

- Direction: **Money In** or **Money Out**.
- Amount in INR, person/party, date, exact time, method (Cash, UPI or configured other), category/reason, description, reference and note.
- Backdating is allowed; the creation timestamp is preserved separately.
- Suggested Money In categories: Customer Payment, Money Received From Owner, Repayment Received, Other Money Received.
- Suggested Money Out categories: Money Given to Owner, Stock Purchase, Expense Payment, Cash Handover, Repayment Given, Other Money Given.
- Categories are configurable in Settings.

The app does **not** assume every incoming amount is a sale, or every outgoing amount is an expense.

### Search, filters and summaries

- Search by person, amount, description or reference.
- Filter by exact date, date range, Today, Yesterday, 7 days, This month, Last month, All time or Custom.
- Filter by direction, category and method.
- Daily and monthly summaries show money in/out, cash in/out, UPI in/out, opening/closing balances where known, and entry count. In minus out is never labelled profit.
- Running balances are tracked separately for physical cash and UPI. An incomplete opening balance is flagged rather than guessed.

### Corrections and voids

- Editing creates a correction record: original values, corrected values and correction time are kept.
- Voiding requires a reason and recalculates balances; the entry remains in history.
- Cash-to-UPI movements reduce one balance and increase the other without being treated as income or an ordinary expense.
- Sale payments, expenses, stock purchases and handovers are separate linked entries. They are never duplicated into manual transactions. Cash↔UPI movements are recorded once with the dedicated **Cash / UPI transfer** action, which moves both balances without inflating money-in or money-out totals.

### Owner handovers

- Quick form for person, amount, date/time, Cash or UPI, reason and note.
- Cash handovers reduce the physical cash balance; UPI handovers stay separate.
- Handovers are custody transfers, not ordinary expenses.
- History is preserved and idempotency keys prevent duplicate handovers on retry.

### Customer payments and outstanding balances

- Each sale shows total, received, refunds and remaining.
- Pending customer payments appear on the Dashboard and in Sales History.
- Later payments record the actual time, method and linked sale, update the remaining balance and appear once in Money History.
- Unpaid amounts are not counted as money received.

---

## Offline-first behaviour

- The PWA shell, product catalogue and settings are cached by a service worker (`college-cart-shell-v16`).
- **New Sale**, **Expenses**, **Money History transactions** and **cash handovers** can be recorded while offline. They are stored in an IndexedDB outbox (localStorage fallback) and appear immediately with a pending marker.
- Offline queues are namespaced by account, so two accounts on the same browser never share pending records.
- On reconnect the queue syncs automatically, with manual **Sync now** available in Settings & Backup. Every queued operation carries a stable idempotency key, so retries cannot create duplicates.
- Stock is adjusted in the cached catalogue when an offline sale is saved. The server re-validates stock when it syncs. Conflicts remain in the queue with their error and can be reviewed or discarded explicitly.
- A failed sync is shown as **Sync failed** with the reason. Offline records are never deleted silently.
- The app distinguishes three cases: the device is offline, the local server is unreachable, and the external College Cart website is unavailable. Only the first two affect this app; the app has no automated dependency on the website.
- Other writes (returns, later payments, stock receipts, adjustments, delivery edits, verification decisions) require a reachable server.

Offline limitations: the first visit must be online to install the shell, clearing site data deletes unsynced local records, and there is no device-to-device sync. The server database is the record of truth once items synchronize.

---

## Reports

Simple business reports for a selected period:

- Sales (net of returns) and sales count.
- Money received, with sale payments distinguished from other money in.
- Ordinary expenses and stock purchases, shown separately.
- Money given to people, including handovers.
- Pending customer payments and outstanding totals.
- Cash and UPI movement with opening/closing balances where known.
- Daily net sales and monthly sales/expense summaries.
- Best-selling products by quantity after returns.
- Current stock with In Stock, Low Stock and Out of Stock states.
- CSV exports for sales, money history, expenses, payments, inventory, stock movements, receivables, reconciliation and monthly/daily summaries. Every CSV uses a UTF-8 BOM and prefixes formula-leading cells to prevent spreadsheet injection.

There are no profit, COGS, margin or valuation reports.

---

## Settings & Backup

- Business display name.
- Business timezone (displayed read-only; set `CARTFLOW_BUSINESS_TIMEZONE` to change it).
- Payment methods.
- Expense categories, money-in categories and money-out categories.
- Default low-stock threshold.
- Optional opening cash balance, opening UPI balance and effective date. Running balances are marked incomplete until both opening values are set.
- Offline queue with **Sync now**, per-record error and explicit discard.
- Audit history (last 100 changes).
- Backup and restore:
  - Create and download a consistent SQLite snapshot.
  - Uploaded backups are validated (integrity check, required tables, Alembic revision) before use.
  - Restore requires typing `REPLACE`, creates a `before-restore-*` snapshot first, then replaces the database and upgrades the schema. Restore never happens silently.
  - Upload limit is 250 MB.
- CSV exports are available from Reports and Expenses.

---

## Money rules

- Net sales = gross sales − returns value.
- Money received = sale payments received + other money received; outstanding balances are not included.
- Ordinary expenses exclude stock purchases. Stock purchases are already reflected in inventory cost when items are sold, so they are reported separately from ordinary operating expenses.
- Cash available = opening cash + cash receipts − cash refunds − cash expenses − cash stock payments − cash handovers + other cash in − other cash out.
- UPI available = opening UPI + UPI receipts − UPI refunds − UPI expenses/purchases − UPI handovers + other UPI in − other UPI out.
- Expected cash drawer = opening cash + cash received − cash refunds − cash expenses − cash handovers.
- Handovers are custody transfers, not expenses.
- Physical cash and UPI are always tracked separately.
- A cash↔UPI transfer changes the two balances without being income, an ordinary expense or part of money-in/money-out totals. Running balances require known opening balances; otherwise the app flags them as incomplete.
- There is no profit, gross-profit, net-profit, margin or COGS figure in the interface. The app is a record-keeping aid, not accounting software.

---

## Configuration

All settings are optional. Copy `.env.example` to `.env` only if you need to change defaults.

| Variable | Default | Purpose |
| --- | --- | --- |
| `CARTFLOW_DATABASE_URL` | `sqlite:///.../college_cart.db` | Business database claimed by the first account |
| `CARTFLOW_ACCOUNTS_DB_PATH` | `.../accounts.db` | Account store (emails and password hashes only) |
| `CARTFLOW_USERS_DATA_DIR` | `.../user_data` | Databases for accounts created after the first |
| `CARTFLOW_SECRET_KEY` | empty | Session-signing secret. Empty generates and stores one in `accounts.db` |
| `CARTFLOW_SESSION_DAYS` | `30` | How long a sign-in cookie stays valid |
| `CARTFLOW_ALLOW_SIGNUP` | `true` | Set to `false` to stop new registrations after your accounts exist |
| `CARTFLOW_PASSWORD_ITERATIONS` | `600000` | PBKDF2 work factor for password hashing |
| `CARTFLOW_COOKIE_SECURE` | `false` | Force `Secure` cookies when HTTPS is terminated before the app |
| `CARTFLOW_BUSINESS_TIMEZONE` | `Asia/Kolkata` | Business day grouping, dashboard ranges, opening balances, money reports |
| `CARTFLOW_DEV_CORS` | `false` | Allow another local dev origin; keep off in normal use |
| `CARTFLOW_PUBLIC_BASE_URL` | empty | Public HTTPS origin used for canonical URLs, `sitemap.xml` and social share images. Empty derives it from each request |
| `CARTFLOW_ALLOW_INDEXING` | `false` | Publishes only the sign-in pages to crawlers. Signed-in screens stay `noindex` |

Set the timezone before entering data. Changing it later regroups existing UTC timestamps into different business days.

---

## Custom domain and page metadata

Every screen has a clean URL and its own metadata. The server renders the correct title, description, canonical link and structured data for direct visits and crawlers, and the client updates them during in-app navigation.

| URL | Screen |
| --- | --- |
| `/login` | Sign in |
| `/signup` | Create account |
| `/dashboard` | Dashboard (`/` redirects here) |
| `/new-sale` | New Sale |
| `/sales` | Sales History |
| `/sales/{id}` | Sale detail |
| `/inventory` | Inventory |
| `/expenses` | Expenses |
| `/money-history` | Money History |
| `/reports` | Reports |
| `/settings` | Settings & Backup |

Signed-in screens require a session; visiting one without a cookie redirects to `/login?next=…`. Unknown URLs return HTTP 404 with a custom page, and unknown `/api/` paths return a JSON 404.

Generated files:

- `/sitemap.xml` — the two public sign-in pages, using `CARTFLOW_PUBLIC_BASE_URL` when set. Business screens and individual sales are excluded because they are private records.
- `/robots.txt` — `Disallow: /` while indexing is off; with indexing enabled it allows only `/login` and `/signup`, disallows every app route and points to the sitemap. `/robot.txt` redirects to `/robots.txt`.
- `/llms.txt` — a plain-language summary for language models.
- `/favicon.ico`, `/icons/*` — icon set for tabs, shortcuts and home-screen installs.
- `/social/college-cart-share.png` — 1200×630 Open Graph and Twitter card image with alt text.

Every app page carries `noindex, nofollow`, `LocalBusiness` and `BreadcrumbList` JSON-LD, breadcrumb navigation and exactly one `<h1>`. The sign-in pages are the only crawlable pages.

### Pointing a domain at it

1. Put the app behind a reverse proxy (Caddy, nginx, Tailscale Funnel, Cloudflare Tunnel) that terminates HTTPS and forwards to `127.0.0.1:8000`.
2. Set `CARTFLOW_PUBLIC_BASE_URL=https://your.domain` so canonical, sitemap and share URLs never fall back to the proxy's internal address.
3. Set `CARTFLOW_COOKIE_SECURE=true` if the proxy terminates HTTPS, and consider deleting `CARTFLOW_SECRET_KEY` reuse across environments.
4. Keep `CARTFLOW_ALLOW_INDEXING=false` unless you deliberately want the sign-in pages indexed. Business pages stay private either way.
5. Keep `accounts.db`, `college_cart.db` and `user_data/` on persistent disk. Do not deploy on an ephemeral filesystem, because each restart would begin with no accounts and no data.

> [!WARNING]
> Accounts and HTTPS protect the app, but it is still a single-server SQLite application. Use a reverse proxy with TLS, set a strong `CARTFLOW_SECRET_KEY`, close signup when you are done, and keep backups somewhere private.

---

## Security and privacy

- Every account has a separate SQLite database. Requests open only the signed-in account's file, so a missing filter cannot expose another account's records.
- Passwords are hashed with PBKDF2-HMAC-SHA256 (600,000 iterations, random salt) and never stored or logged in plain text. Login and registration are rate-limited.
- Sessions use a signed, HttpOnly, SameSite=Lax cookie. Unsafe `/api` requests are rejected when they come from another origin, which blocks cross-site request forgery.
- Search engines only ever see the sign-in pages. Signed-in screens send `noindex, nofollow` and `/robots.txt` disallows crawling while indexing is off.
- Responses send a strict Content-Security-Policy, `X-Frame-Options: DENY`, a referrer policy and a Permissions-Policy that disables camera, microphone and geolocation.
- No hardcoded credentials, API keys, analytics or external customer-data transmission.
- Customer name, phone and room fields are optional; anonymous walk-in sales need no personal data.
- All user text is escaped in the UI, SQL uses the ORM, and CSV/backup paths are validated.
- Backups contain one account's full business data. Store downloaded backups somewhere private; delete old copies you no longer need. `accounts.db` holds password hashes and should be protected like the rest of the data directory.
- Restore and cancellation are destructive-by-design and always require explicit confirmation; audit history is preserved for normal corrections.
- All timestamps are stored in UTC and converted to the business timezone for display and day grouping.
- Keep the server bound to `127.0.0.1` or behind an HTTPS reverse proxy. Authentication does not replace TLS on a shared network.

---

## Project structure

```text
CartFlow/
├─ app/
│  ├─ main.py                 FastAPI app, auth pages, SEO routes, static frontend, error handling
│  ├─ seo.py                  Per-route metadata, JSON-LD, sitemap, robots, llms.txt
│  ├─ accounts.py             Account store and password hashes
│  ├─ security.py             Hashing, session cookies, validation and rate limits
│  ├─ userdata.py             Per-account SQLite engines and migrations
│  ├─ models.py               SQLAlchemy models, enums, indexes, constraints
│  ├─ schemas.py              Pydantic request/response contracts
│  ├─ database.py             SQLite engine, WAL, foreign keys, sessions
│  ├─ config.py               Environment-based settings
│  ├─ bootstrap.py            Alembic upgrade + optional demo seed
│  ├─ seed.py                 Fictional demo products only
│  ├─ routers/                auth, sales, products, inventory, expenses, money,
│  │                          cash, deliveries, reconciliation, reports,
│  │                          settings, backup
│  ├─ services/               Business rules, money ledger, financial summaries,
│  │                          sync, backup
│  └─ audit.py                Audit/sync helpers
├─ alembic/
│  └─ versions/               1d82829431ba_initial_schema.py
│                             7b41f0c2d9aa_money_history_ledger.py
├─ frontend/
│  ├─ index.html              App shell, navigation and metadata template
│  ├─ auth.html               Sign-in and sign-up page
│  ├─ css/app.css             Design system and responsive layouts
│  ├─ js/                     ES modules: router, API, store, IndexedDB, sync, auth, UI
│  ├─ js/pages/               dashboard, new-sale, sales, sale-detail, inventory,
│  │                          expenses, money-history, reports, settings, not-found
│  ├─ icons/                  Favicons, PWA icons and the installable maskable icon
│  ├─ social/                 Open Graph / Twitter share image (1200×630)
│  ├─ favicon.ico             Root favicon
│  ├─ sw.js                   Service worker (network-first shell cache, v16)
│  └─ manifest.webmanifest    Installable PWA metadata
├─ tests/                     Pytest suite (isolated temporary databases)
├─ accounts.db                Account store (created on first signup)
├─ user_data/                 Databases for accounts after the first
├─ backups/                   Manual and before-restore snapshots
├─ uploads/                   Temporary validated restore uploads
├─ requirements.txt
└─ README.md
```

---

## Using it day to day

1. Start the server, open `http://127.0.0.1:8000` and create the first account. That account keeps any existing records.
2. Check products in **Inventory**; add products or receive stock.
3. Use **New Sale** for walk-ins and delivery orders. To link a website order, choose "Website order" and paste the order ID; the app warns if it is already recorded.
4. Record payments as they arrive. The app supports full, partial and unpaid sales and multiple payment methods.
5. Use **Sales History** to review balances, verify website orders manually and open a sale to add payments or process returns.
6. Record ordinary costs in **Expenses**. Buy stock through **Inventory → Receive stock** so the purchase stays linked.
7. Use **Money History** for owner handovers, money from or to the owner, repayments and other money movements. Check cash and UPI balances at close.
8. Use **Reports** for a simple period summary and CSV exports.
9. Create a backup regularly in **Settings & Backup** and download a copy.

Install the PWA from the browser (install icon in the address bar) for a standalone window. Installation and service workers require `localhost` or HTTPS.

---

## Troubleshooting

| Problem | Fix |
| --- | --- |
| Port 8000 already in use | Stop the other process (`netstat -ano | findstr :8000`) or run with `--port 8010` and open that port |
| `ModuleNotFoundError` | Activate the virtual environment and run `pip install -r requirements.txt` |
| `database is locked` | Close other app/server instances and retry; SQLite WAL allows readers, but only one writer. Do not delete `-wal`/`-shm` while the server is running |
| Old styles or pages after an update | Hard reload (`Ctrl+F5`), or use DevTools → Application → Service Workers → Update/Unregister. The current cache is `college-cart-shell-v16` |
| Offline queue item shows an error | Open **Settings & Backup → Offline queue**, read the error (for example a stock conflict or duplicate order ID), retry after correcting data, or discard only if the record is genuinely invalid |
| Expense category "Stock purchase" is missing | Record stock purchases from **Inventory → Receive stock**; manual stock-purchase expenses are rejected to prevent double counting |
| Cash available looks wrong | Set both opening cash and opening UPI balances plus an effective date in Settings & Backup |
| Backup validation fails | Use a SQLite backup created by this app; it must pass integrity checks and contain the app tables and `alembic_version` |
| Restore rejected | The confirmation field must contain exactly `REPLACE` |
| Wrong business day boundaries | Set `CARTFLOW_BUSINESS_TIMEZONE` before entering data; changing it later shifts grouping |
| Reports show zero after restore or reset | Expected on a clean database; record sales or restore a backup |

---

## Limitations

- Single-machine design: SQLite plus a local server, no multi-device or real-time cloud sync. Accounts keep data private from each other, but they share the same server.
- Authentication is built in, but there is no password reset, email verification, two-factor login or admin console. If a password is lost and no session is active, restore an account database backup only after creating a new account; account records themselves are not part of business backups.
- No automatic College Cart website import, scraping or sync. Website order IDs are entered manually and verified manually.
- Offline writes are limited to sales, expenses, money transactions and handovers. Other financial changes require the server.
- One business currency (INR by default); no tax/GST filing, payroll, invoicing or accounting-ledger features.
- Backup restore replaces the entire database, including audit history and settings; it is intentionally guarded, not a merge tool.
- The app is a record-keeping aid, not a substitute for professional accounting or legal advice.
