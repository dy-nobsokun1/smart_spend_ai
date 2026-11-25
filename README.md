# SmartSpend AI

A local, single-user expense workspace for USD and Cambodian riel. Built with vanilla HTML/CSS/JavaScript, FastAPI, SQLAlchemy with MySQL support, Google Gemini receipt extraction, and locally bundled Chart.js.

## Run on Windows

Requires Python 3.12 or newer. From this project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. API documentation is at **http://127.0.0.1:8000/docs**.

On macOS/Linux, use `python3` and `.venv/bin/python` instead. If Windows virtual environment creation fails at `ensurepip`, bootstrap with `python -m pip --python .venv install -r requirements.txt`.

The default development configuration uses SQLite at `data/smartspend.db` and adds clearly labeled sample data on the first run. This makes the application usable without database credentials. `DEMO_DATA=true` only seeds when **all three application tables are empty**; it does not overwrite records. The demo badge reflects the seeding configuration. Set `DEMO_DATA=false` and use a **new database** to start with empty personal records. Changing this flag does not delete sample records already saved.

## Use MySQL

Install MySQL 8+ or start the optional local database with Docker:

```powershell
docker compose up -d db
```

The Compose configuration is for local development and uses the credentials below. Alternatively, provision an empty UTF-8 database and an application user yourself:

```sql
CREATE DATABASE smartspend CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'smartspend'@'localhost' IDENTIFIED BY 'replace-with-your-password';
GRANT ALL PRIVILEGES ON smartspend.* TO 'smartspend'@'localhost';
```

Set in `.env` and restart the server:

```dotenv
DATABASE_URL=mysql+pymysql://smartspend:smartspend_local@127.0.0.1:3306/smartspend?charset=utf8mb4
DEMO_DATA=false
```

Use your actual credentials if you provisioned MySQL yourself. Percent-encode special characters in URL passwords. The application creates its tables at startup; the database must already exist. SQLite records are **not** automatically migrated when switching databases. Export transaction CSVs before switching if you want to import those transactions into the new workspace; budgets and goals need to be recreated. The schema is an initial version; future schema changes will require migrations.

## Enable receipt scanning

Create a Gemini API key in Google AI Studio, then set:

```dotenv
GEMINI_API_KEY=your-key
GEMINI_MODEL=gemini-3.8-flash
```

Restart the server. The default is [Gemini 3.8 Flash](https://aistudio.google.com/docs/models/gemini-3.8-flash). The model is configurable so you can select an available image-capable Gemini model supporting structured output. The key stays on the backend. Do not commit `.env`.

Choose **Receipt scanner**, upload a JPG, PNG, or WebP image (up to 10 MB and 25 megapixels), and review the extracted merchant, date, total, currency, and item notes. Images are sent to Google Gemini; the application does not persist the image. The scanner returns one purchase total, avoiding double-counting dual-currency receipt totals. Missing dates, totals, or currencies require correction. Gemini output can be wrong, especially on low-quality photos or Khmer print: verify every field. Nothing is saved until confirmation. Receipt scanning is unavailable until a key is configured; it never pretends to scan a sample image.

After confirming a receipt, SmartSpend opens Transactions at the saved record's month and currency, highlights the record, and retains that view when you refresh. A receipt dated in a previous year will appear in that year's month, not the current month. Re-scanning a matching receipt opens the existing transaction and states that no new transaction was added. Correct an incorrectly extracted date during review or by editing the saved transaction.

## Features

- Responsive overview with monthly income, expenses, net income, category budget remaining, daily spending comparisons, and category charts.
- USD and KHR always queried and summarized separately. There is no currency conversion or combined balance.
- Create, search, filter, edit, delete, and export transactions; paginated transaction list.
- Manual expenses include a merchant name and editable purchased items with a price for each line. The form calculates an exact items subtotal; the purchase total can include tax, tips, or discounts. Use the full line price when buying multiple units (for example, “Coffee × 2” with the price for both coffees).
- CSV upload, field validation, editable previews, row selection, atomic confirmation, and duplicate detection.
- Khmer and English receipt extraction with Gemini structured output and mandatory review.
- Receipt review includes editable merchant, item names, item prices, and the printed receipt total. Item prices use the purchase currency. An unreadable item price remains blank until corrected. A difference between the subtotal and purchase total is shown for review.
- Category suggestions from a small multinomial Naive Bayes model using English tokens and Khmer character trigrams. Saved non-demo expense classifications become training examples. This starter model is not a calibrated financial classifier. Dashboard insights are calculated summaries, not Gemini advice.
- Category budgets scoped to month and currency. Saving an existing combination updates its limit. Budget remaining subtracts only spending in budgeted categories. Expenses without a budget remain in the total expenses card.
- Savings goals scoped to currency, with target, saved amount, and optional deadline. Updating progress is a planning entry; it does not transfer funds or create a transaction.
- Exact decimal financial calculations in Python and `NUMERIC(16,2)` storage. USD allows two decimal places; KHR uses whole riel. Floating point is used only for chart rendering and displayed ratios.

### CSV format

UTF-8, comma-separated, header row required. Maximum 1,000 transactions / 2 MB. Amounts are positive; use `kind` to mark income. Omitted categories receive a suggestion. Empty or unknown values can be corrected in the review screen. Check **Keep** to enable editing a rejected row. Entirely empty imports, missing columns, and mismatched column counts are rejected.

```csv
date,description,amount,currency,kind,category,note
2026-11-12,Brown Coffee,4.50,USD,expense,Food & drinks,Morning coffee
2026-11-12,ផ្សារថ្មី,25000,KHR,expense,Groceries,Vegetables
2026-11-01,Monthly salary,1800.00,USD,income,Income,
```

Required: `date`, `amount`, `currency`, and either `merchant` or `description`. Optional: `kind` (defaults to expense), `category`, `note`, `items`, `account_id`. Legacy files with only `description` use it as the merchant name. Dates are ISO `YYYY-MM-DD`; amounts have no symbols or thousands separators. Sample: `examples/transactions.csv`, also downloadable from the import screen.

Exports also include the merchant, paying `account_id`, and an `items` column containing a JSON array such as `[{"name":"Coffee","price":"4.50"}]`. Standard CSV quoting applies. Importing an exported file preserves these item names and prices. Account IDs are specific to a workspace: select the correct account during CSV review when importing into another database. Files without an account use the default account for each currency.

Import duplicate matching uses date, case-insensitive description, amount, currency, and type. Exact matches within a batch or against previous imports are skipped, even if the category differs. A matching purchase with no item details can be enriched with newly reviewed items without creating another expense. Existing item details are preserved; use Edit to change them. Two legitimate identical purchases on the same day can therefore match; add the second manually when necessary. Manual entries are not deduplicated. Editing an imported transaction retains its original import fingerprint. Export protects spreadsheet formula-like descriptions by prefixing an apostrophe; that prefix may remain when reimported.

### Existing workspace upgrade

On startup, an additive migration creates the `transaction_items` table and adds the merchant field if needed. Earlier description values become merchant names. Existing transactions, dates, amounts, currencies, notes, and import fingerprints are preserved. Older receipt item text remains in its original note; add structured items by editing the transaction or rescanning it. No item prices are guessed from old notes.

## Expected expenses and reserves

The four financial concepts are independent:

| Concept | What it records | Effect on actual balance |
| --- | --- | --- |
| Actual expense | A recorded payment | Deducted once |
| Expected expense | An unpaid obligation or estimate | None |
| Reserved funds | Money explicitly allocated toward an obligation | None; reduces available funds |
| Category budget | A monthly spending limit | None |

For example, a tuition obligation can have an expected amount of **$600**, only **$200 reserved**, and **$400 unfunded**. Its category budget is an independent spending limit. Savings goal progress remains an independent planning tracker as well.

### Accounts and balance calculations

Each account has one currency and an opening balance. Account balances use all recorded transactions dated **today or earlier**, using Cambodia's current date. They do not depend on the dashboard's selected month:

```text
Actual balance    = Opening balance + completed income - completed expenses
Reserved balance  = Net allocations toward active, unpaid expected expenses
Available balance = Actual balance - Reserved balance
Unfunded amount   = Expected amount - Reserved amount
```

The backend uses Decimal arithmetic and persists money in `NUMERIC(16,2)`. USD permits cents; KHR permits whole riel. Totals are never combined across currencies. Multiple accounts can be summarized within a currency, but allocations can only use the specified account's unallocated money. Account A cannot fund an obligation in Account B.

Opening balances represent money held **before** the entered transactions. They do not appear as income, and no actual bank connection or reconciliation is implied. Future-dated transactions do not fund today's reserves or qualify as completed payments. The overview distinguishes current balances from its existing monthly income, spending, and budget charts.

### Planning, funding, and payment

Use **Expected expenses → Plan an expense** to enter the name, description, expected amount, account, currency, category, due date, fixed/estimated type, recurrence, and optional in-app reminder preference.

- **Gradual reservation:** reserve zero or a chosen amount initially, then add or release funds manually.
- **Full reservation:** allocate the full expected amount immediately, if the account has enough available funds.
- Funding status is derived: Planned, Partially reserved, or Fully reserved. Paid and Cancelled are lifecycle states. Overdue and reminder flags are independent and do not release funds.
- Editing the expected amount does not allocate more money. Release excess funds before lowering a target below its existing reserve, or before moving a funded obligation to another account/currency.
- Cancel releases the reserve, preserves its history, and does not record spending.
- Pay / link payment can create an expense with the confirmed actual amount, or associate an existing expense from the same account/currency. Linking does not deduct money again.
- Completion releases the entire reserve, records or links one actual expense, marks the occurrence paid, and creates any next recurring occurrence **atomically**. Payment amounts may differ from the estimate. A new payment that would leave available funds negative requires explicit confirmation.
- Paid records retain their linked payment. Its amount, date, account, currency, type, and category cannot be changed, and the linked transaction cannot be deleted. Merchant names, item details, and notes can be corrected. Unlinking/reopening paid obligations is not implemented.

With an actual balance of $1,000 and a $250 reserve, available funds are $750. Paying $250 leaves actual $750, reserved $0, and available $750. If $50 was reserved but the actual payment is $42, the final actual balance is $958 and the reserve is zero. No second $50 expense is recorded.

Allocations form an append-only journal: initial/add entries are positive and release/payment/cancellation entries negative. Entries retain the account, currency, reason, and UTC timestamp. Accounts with financial history cannot be deleted. SQLite foreign keys are enabled; MySQL uses the model's foreign key relationships.

### Recurring definitions and reminders

One-time, weekly, monthly, and yearly plans are supported. A recurring definition is separate from its occurrences. Settling or cancelling an occurrence generates exactly one next, **unfunded** occurrence unless the definition is stopped. Repeated requests, refreshes, and restarts do not generate duplicates. Monthly dates keep the original anchor: January 31 → February 28 → March 31. Yearly leap-day dates are clamped to the end of February as necessary.

Changes to one occurrence do not rewrite the recurring definition's original settings. Stop future repeats preserves existing occurrences; cancelling an occurrence can also stop its definition. There is no background scheduler generating a calendar of unpaid occurrences: the next occurrence is generated after the current one is settled or cancelled. Reminder preferences produce in-app due/overdue indicators only; emails, push notifications, and background reminders are not implemented.

### Receipt matching

Receipt and payment-image review uses the existing Gemini extraction, then deterministic name, amount, date, category, currency, and account checks to suggest outstanding obligations. Matching makes no additional Gemini requests. The user must explicitly select an expected expense; **Record independently** is the default. The user can choose any outstanding expense in the selected account, even when it is not a suggested match.

Confirming a selected match performs the same atomic settlement as Pay / link payment. A previously imported receipt or an exact, unambiguous manual payment can be reused instead of inserted again. Ambiguous existing payments require the user to choose through Pay / link payment. No expected expense is marked paid merely because extraction or matching ran.

### Reserve schema upgrade

Restart the existing application normally; `initialize_database()` performs the idempotent additive upgrade. No database reset or manual SQL is required for the supported SQLite/MySQL setup.

- New `accounts` table, with zero-opening-balance **Main USD** and **Main KHR** defaults.
- New nullable `transactions.account_id` foreign key and index; existing transactions are assigned to the default account matching their currency. Existing amounts, dates, items, notes, categories, and default-account import fingerprints remain intact.
- New `expected_expenses` table for obligations/occurrences, including due date, expected amount, funding preference, lifecycle state, account/currency, reminder preference, and timestamps. The linked actual transaction is unique, so one payment cannot complete two obligations.
- New `reserve_allocations` table for signed virtual allocations and release history.
- New `recurring_expenses` table for repeat definitions; `(recurring_id, occurrence)` is unique on occurrences.

No sample reserves or opening balances are invented for existing workspaces. Review the default account balances and set opening balances only when your existing records do not already include that money. Import fingerprints remain compatible with earlier default-account records; new imports into custom accounts include the account in their identity.

All finance-changing endpoints acquire the SQLite writer lock or MySQL account row locks before reading funds. These locks, database constraints, atomic commits, and paid-state checks protect against concurrent over-allocation, duplicate payment links, and repeated completion requests.

### Feature files and verification

New files:

- `backend/ledger.py`: shared account assignment, transaction serialization, and import identities.
- `backend/reserves.py`: authoritative balances, reserve funding, settlement, recurrence, and deterministic matching.
- `backend/expected_api.py`: account and expected-expense API routes.
- `frontend/expected.js`, `frontend/expected.css`: balances, account management, expected expense forms, history, and responsive layout.
- `tests/test_reserves.py`: financial invariants, lifecycle, recurrence, account/currency separation, receipt matching, and concurrency tests.

Updated files: `backend/models.py`, `backend/schemas.py`, `backend/database.py`, `backend/migrations.py`, `backend/main.py`, `backend/seed.py`, `frontend/app.js`, `frontend/index.html`, `tests/conftest.py`, `scripts/browser_check.py`, and this README. No new dependencies were added.

Verification for this implementation: **73 automated tests passed**. Headless Microsoft Edge browser checks also passed for the original transaction/import/item/budget/goal workflows plus accounts, plan creation/editing/funding/releasing, payment creation/linking, cancellation, history, recurrence, mobile layout, and explicit receipt matching. Gemini extraction is stubbed during tests. File-backed SQLite tests issue concurrent requests to verify funding and payment idempotence. All eight model tables were successfully compiled as MySQL DDL. Live Gemini calls and a live MySQL database/lock environment have **not** been verified in these checks; DDL compilation does not replace integration testing.

### Local scope

This version has **no login or per-user authorization**. Run bound to `127.0.0.1` for a personal workspace. Before a shared or internet deployment, implement authentication, record ownership, HTTPS, request limits, database migrations, and backups. Local use requires no cloud deployment. Chart.js is bundled; Google Fonts uses an optional internet stylesheet and falls back to system fonts. Receipt scanning requires an internet connection and a Gemini account.

## Development and verification

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest -q
node --check frontend/app.js
node --check frontend/items.js
```

API tests use isolated in-memory databases and stub Gemini; they never use real credentials or edit personal records. Browser checks run against a separate disposable database with the installed Microsoft Edge browser. Run `python scripts/browser_check.py` after installing development requirements. The browser test starts its own server on port 8001, exercises the main user flows, and saves desktop/mobile screenshots under ignored `test-results/`.

```text
backend/           FastAPI routes, validation, persistence, category model, demo data
frontend/          Vanilla HTML, CSS, JS, bundled Chart.js
tests/             Isolated API and financial correctness tests
scripts/           Browser smoke test
examples/          Sample transaction CSV
```

## Implementation references

- [FastAPI relational databases](https://fastapi.tiangolo.com/tutorial/sql-databases/)
- [SQLAlchemy MySQL dialect](https://docs.sqlalchemy.org/en/20/dialects/mysql.html)
- [Gemini structured outputs](https://ai.google.dev/gemini-api/docs/structured-output)
- [Gemini image understanding](https://ai.google.dev/gemini-api/docs/image-understanding)
- [Chart.js integration](https://www.chartjs.org/docs/latest/getting-started/integration.html)

Chart.js is included under its MIT license in `frontend/vendor/Chart.LICENSE.md`.
