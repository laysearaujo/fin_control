# Guardião — Technical Documentation

Guardião is a personal finance tracker built with Django. It tracks checking-account
cash flow, credit card invoices (one or more cards), fixed/recurring bills and income,
one-off bills (including installment plans outside of credit cards), and "caixinhas"
(virtual savings boxes) with real, event-based yield tracking.

This document explains the domain model, the business rules that aren't obvious from
the code alone, and how the pieces fit together. It exists because several real bugs in
this app came from two sources: (1) matching business meaning by parsing free-text
names/descriptions instead of using explicit flags, and (2) reusing a number computed
for one purpose (e.g. category spend analysis) in a context that needed a different
number (e.g. checking-account balance). Both patterns are called out below wherever
they're relevant, so they don't get reintroduced.

## Table of Contents

1. [Tech Stack](#tech-stack)
2. [Project Structure](#project-structure)
3. [Getting Started](#getting-started)
4. [Data Model](#data-model)
5. [Core Business Rules](#core-business-rules)
6. [Pages & Features](#pages--features)
7. [Shared UI Infrastructure](#shared-ui-infrastructure)
8. [Migrations](#migrations)
9. [Known Limitations](#known-limitations)

---

## Tech Stack

- **Backend:** Python, Django 6.0
- **Database:** SQLite (`db.sqlite3`, at the project root)
- **Frontend:** Server-rendered Django templates, Bootstrap 5, vanilla JS, Chart.js
  (loaded from CDN, no bundler/build step)
- **Date math:** `python-dateutil` (`relativedelta`) for month arithmetic
- **Language split:** all Python identifiers (models, fields, view functions, variable
  names) are in English; all user-facing text (templates, `verbose_name`, labels,
  messages) is in Portuguese (pt-br). `LANGUAGE_CODE = 'pt-br'` in `core/settings.py`
  controls Django's own `|date` template filter locale; a hand-written `MESES_PT` /
  `MESES_PT_ABREV` dict in `finance/views/reports.py` covers month names built in
  Python code, since `strftime('%B')` depends on the OS locale and isn't reliable.

## Project Structure

```
core/                   Django project (settings, root urls)
finance/                The one Django app that holds everything
  models.py             All models (see Data Model below)
  forms.py              ModelForms; BootstrapModelForm auto-applies Bootstrap classes
  context_processors.py Injects the navbar quick-add forms + category flag map globally
  views/                 Split by domain (not one giant views.py)
    dashboard.py          Main dashboard (balance forecasting cascade)
    transactions.py       Expenses, income, statement (extrato)
    savings_boxes.py       Caixinhas: CRUD, withdraw, self-loan, yield tracking
    credit_cards.py        Card CRUD + invoice payment
    categories.py          Category CRUD
    fixed_expenses.py       Recurring bills CRUD + "pay this month"
    fixed_incomes.py        Recurring income (salary) CRUD
    one_off_bills.py        Non-recurring "extra" bills, optionally installment-split
    reports.py              Category report (Análises), annual report (Visão Anual)
    annual_analysis.py      12-month cash flow projection + purchase simulator
  templates/            One template per page, all extending base.html
  migrations/           Gitignored (see Migrations below) — regenerate with `migrate`
```

There is no REST API, no JS framework, and no build step. Every interactive behavior
(toggles, conditional fields, quick-add modals) is a `<script>` block in `base.html` or
the page's own template, operating on plain DOM elements.

## Getting Started

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Then open `http://127.0.0.1:8000/`. `finance/migrations/` is gitignored, so a fresh
clone needs `migrate` to build the schema from scratch — there is no seed data.

## Data Model

### `Category`
A spending bucket (Alimentação, Lazer, ...) with a `monthly_cap` (budget ceiling).

- **`reverse_logic`** (bool): marks a category as a savings/contribution ("Aporte")
  category rather than a normal expense category. When true:
  - The category's spend-vs-cap coloring flips (spending *more* than the cap is good —
    you're contributing more to savings — so the UI shows green when over, red when
    under, the opposite of a normal expense category).
  - The "Nova Despesa" form/modal reveals a **Caixinha de Destino** (target savings
    box) field, so the transaction can route money into a `SavingsBox`.
  - This flag is looked up directly (`category.reverse_logic`, or via the
    `categoryReverseLogicMap` JS map described in
    [Shared UI Infrastructure](#shared-ui-infrastructure)) — never by checking whether
    the category's *name* contains "aporte"/"reserva"/"investimento". An earlier
    version of the show/hide JS did exactly that name-matching, which is fragile
    (rename the category and the behavior silently breaks) and was replaced.

### `CreditCard`
One row per physical card. `closing_day` + `due_day` let
`get_actual_due_date(purchase_date)` decide which invoice month a purchase lands in
(if bought on/after the closing day, it rolls to next month's invoice). The app
supports **multiple cards** — every invoice-related calculation in `dashboard.py` and
`credit_cards.py` is done per-card, not as one lump sum (see
[Core Business Rules](#credit-cards-multiple-cards-per-card-invoices)).

### `SavingsBox` ("Caixinha")
A virtual savings pocket. Key fields:

- **`current_balance`**: the live balance, updated by aportes (deposits), resgates
  (withdrawals), and manual "sync to real value" actions.
- **`initial_balance`**: frozen automatically the moment the box is created
  (`SavingsBox.save()` sets it from `current_balance` only when `self._state.adding`
  is true, i.e. only on insert, never on update). This exists so that whatever
  balance a box starts with is never miscounted as *yield* later — see
  [Yield tracking](#savings-box-yield-tracking-not-a-cdi-projection).
- **`cdi_target_pct`**: informational only, no longer drives any projection (an
  earlier CDI-based compound-interest projection was removed — the user found it
  misleading since it wasn't based on what the box actually earned).
- **`is_emergency_reserve`**: marks which box is *the* emergency reserve for the
  Análises page, independent of its name (so renaming the box doesn't break the
  report).
- **`created_at`**: auto-set on creation. Existing boxes (from before this field was
  added) got it backfilled to the migration's run time — their real creation date was
  never recorded, so age-based calculations (yield-in-last-12-months, goal-forecast
  pace) are only as accurate as time-since-that-backfill allows and will sharpen up
  the longer the app is used.

### `SavingsBoxYieldEvent`
One row per manual balance sync ("Atualizar valor hoje" on the Caixinhas list). Stores
the **delta** (`new_value - old_current_balance`) with a date. This is what makes
"yielded in the last 30 days" / "in the last 12 months" answerable — before this model
existed, yield was inferred as a single lump gap with no time dimension.

### `SelfLoan`
"Auto-empréstimo": borrow from a box, pay yourself back with interest via a generated
`FixedExpense`. Lower-traffic feature; less battle-tested than the rest.

### `FixedIncome` / `FixedExpense`
Recurring templates (salary, rent, subscriptions), not the actual monthly occurrences.
`FixedExpense.is_credit_card` + `credit_card` route a subscription onto a specific
card's invoice instead of the checking account.

### `Income` / `Transaction`
The actual dated occurrences. `Income.fixed_income` and `Transaction.fixed_expense`
link a real entry back to the recurring template it settles — **this is how "already
paid/received this month" is detected**, by querying for a matching `Income`/
`Transaction` row, never by comparing description strings.

`Transaction` carries most of the domain's complexity:

- `is_credit_card` + `credit_card` + `installments_count`: on save, if both are set,
  `generate_installments()` fires and creates the `Installment` rows (idempotent —
  checks if installments already exist first).
- `is_invoice_payment` + `invoice_month` + `invoice_year` + `credit_card`: marks a
  transaction as *the* payment that settles one card's invoice for one month. The
  `credit_card` FK here is what lets multiple cards each have their own "paid" status
  for the same month (see below).
- `target_savings_box` / `source_savings_box` / `is_internal_transfer`: see
  [Aportes vs. Resgates](#aportes-vs-resgates-and-why-resgates-dont-touch-checking-balance).
- `one_off_bill`: links back to the `OneOffBill` this transaction settles.

### `Installment`
One row per parcela of a credit-card purchase, with its own `due_date` (already
adjusted for the card's closing day) and `amount`.

### `OneOffBill` ("Conta Extra")
A bill that isn't recurring forever but can still be split across months (e.g. a
12x purchase that isn't on a credit card). `installment_group` (a UUID, shared by
every installment created in the same batch) is what lets editing one installment's
**value** cascade forward to the sibling installments that haven't been paid yet — see
[Installment groups](#one-off-bill-installment-groups). This replaced an earlier
approach that had no grouping field at all and could only identify siblings by parsing
the "(i/N)" suffix Django appended to the title.

---

## Core Business Rules

### "Custo Real" vs. checking-account balance — two different numbers

The category/spend-analysis screens (Análises) and the checking-account balance
screens (Dashboard, Extrato) intentionally use **different definitions of "spend" for
the same underlying transactions**, and conflating them was the root cause of the
session's most significant bug:

- **Custo Real** (used for category caps, the "Patrimônio"/wealth charts, the pizza
  charts): includes *aportes* (money moved into a savings box) and *resgates* (money
  taken back out) as real spend/movement, because from a "where did my money go"
  point of view, money leaving checking to sit in a box is a real outflow worth
  tracking against a budget.
- **Checking balance** (Dashboard's Saldo, the cascading month-to-month balance
  projection): must **exclude resgates** entirely (see next section for why), and
  aportes are a real debit (they did leave checking) so they stay in.

`finance/views/reports.py`'s `_build_month_rows()` computes `month_resgates`
separately and derives `balance_cost = month_cost - month_resgates` specifically for
the balance cascade, while the same month's "Custo Real" figure shown elsewhere still
includes resgates. If you need to add a new screen that touches money, decide up front
which of these two meanings it needs — don't assume they're interchangeable.

### Aportes vs. Resgates, and why resgates don't touch checking balance

- An **aporte** (`Transaction.target_savings_box` set, `is_internal_transfer=False`)
  represents money leaving checking to go into a box. It's a normal debit against the
  checking balance, same as any expense.
- A **resgate** (`Transaction.source_savings_box` set, `is_internal_transfer=True`,
  created in `savings_boxes.withdraw_savings_box`) represents money coming back out of
  a box. The checking-balance calculations (`dashboard.py`, `reports.py`) explicitly
  filter `is_internal_transfer=False` everywhere they sum expenses, so a resgate never
  reduces the checking balance.

  Why exclude it rather than treat it as income? Because the box's money was never
  part of the tracked checking balance in the first place (it lived in
  `SavingsBox.current_balance`), and a resgate might represent cash handed directly to
  someone rather than actually being deposited back into the bank account. Whether
  it's "real spend" is still true from a Custo Real point of view (the money is gone
  from your total net worth), which is exactly why Custo Real *does* include it while
  checking-balance calculations don't — see the section above.

  On the Dashboard's "Últimas Movimentações" feed, a resgate is shown as a normal red
  "-" outflow (matching the Custo Real framing — it's a real loss from your pocket),
  tagged with a small 🐖 "Caixinha" badge for context, not as a neutral/blue
  balance-neutral entry (an earlier version tried that and it was wrong: the user
  correctly pointed out the money really did leave).

### Savings box yield tracking (not a CDI projection)

Earlier versions of the Caixinha detail page projected future earnings from
`cdi_target_pct` via compound interest — pure speculation, unrelated to what the box
actually did. It was removed entirely in favor of only ever showing **real** numbers:

```
current_balance = initial_balance + total_deposited - total_withdrawn + realized_yield
```

Where `realized_yield` is the sum of every `SavingsBoxYieldEvent.amount` for that box.
A yield event is only ever created in one place — the "Atualizar valor hoje" quick
action on the Caixinhas list (`savings_boxes()` view, the `atualizar_saldo` POST
branch) — as the delta between the box's old and new balance. Because of this, the
**"Editar Caixinha" form deliberately does not expose `current_balance` as an editable
field** (`SavingsBoxEditForm` excludes it) — editing the balance through any other path
would change `current_balance` without logging why, breaking the equation above.

The Caixinha detail page (`savings_box_detail.html`) surfaces:
- Lifetime totals (Saldo Inicial, Total Aportado, Total Resgatado, Rendimento, and
  Rendimento as a % of principal).
- Yield in the last 30 days, and yield in the last 12 months (or "desde o início" if
  the box is younger than 12 months) — both computed by summing
  `SavingsBoxYieldEvent` rows in the relevant date window (`_compute_windowed_yield()`
  in `savings_boxes.py`), shared with the compact per-box card on the Caixinhas list.
- A goal-completion forecast, when a `target_amount` is set: it's driven by the box's
  *actual* average monthly growth (`(current_balance - initial_balance) / months
  since creation`), not an interest rate — explicitly requested to replace the old
  speculative version.
- An event-by-event balance line chart, built the same way the Análises page's
  Patrimônio chart is: anchored on today's real balance and walked backwards through
  each deposit/withdrawal, so the line rises/falls exactly where money actually moved.

### Credit cards: multiple cards, per-card invoices

The app supports any number of `CreditCard` rows. Every invoice-shaped calculation is
done **per card**, then summed for display totals:

- `dashboard.py` builds a `cards_invoice` list (one entry per card: its line items,
  total, paid status, next-month accumulating total) rather than one global invoice
  number. `invoice_pending_total` sums only the unpaid cards; a card with nothing due
  this month is excluded from the paid/unpaid ratio badge (a card with R$0 due isn't
  meaningfully "unpaid").
- Paying an invoice (`pay_monthly_invoice(request, cartao_id)`) is scoped to one card:
  it creates a `Transaction(is_invoice_payment=True, credit_card=<that card>, ...)`,
  and "already paid this month" is checked with that same `credit_card` filter. Paying
  one card's invoice must never mark another card's invoice as paid — this was a real
  bug caught mid-session (the original "is *any* invoice paid this month" check, from
  back when there was implicitly only one card, would have silently ignored a second
  unpaid card's balance).
- Credit-card `FixedExpense` subscriptions (Netflix, etc.) are **excluded** from the
  "Contas do Mês" bill list on the Dashboard and treated as always-"paid" there —
  they're never paid individually, only as part of the invoice lump sum, so listing
  them separately as a to-do item was duplicating what the Fatura card already shows,
  and worse, always showed them as perpetually "pending" since no `Transaction` ever
  gets created against them individually.

### One-off bill installment groups

`OneOffBill.installment_group` (a UUID) is shared by every installment created in the
same "Adicionar Conta Extra" submission (`add_one_off_bill`, when "Repetir por quantos
meses?" > 1). When an installment's **amount** is edited
(`edit_one_off_bill`), and it belongs to a group, the new amount is propagated to
every sibling installment in that group whose due date is on/after the edited one's
original due date **and that hasn't been paid yet** (no `Transaction` linked). Already
-elapsed/paid installments are left untouched — the point is "this changed starting
now," not "this changed retroactively." Historical one-off bills created before this
field existed were backfilled into groups by parsing their `"(i/N)"` title suffix
**once**, in a migration — the running app never does that parsing itself.

### "Contas do Mês" sorting and status

Bills (recurring `FixedExpense` + `OneOffBill` for the current month) are sorted
pending-and-overdue-first (`fixed_items_status.sort(...)` in `dashboard.py`), so
what needs attention surfaces above what's already resolved. "Overdue" only applies
to non-credit-card items past their due day in the *current* month — a future or past
month's bills are never flagged overdue (a past month's unpaid bill shows "Não paga"
instead, a future month's isn't due yet).

### Categories don't drive behavior by name

Anywhere behavior used to depend on a category's or box's *name* (string matching for
"aporte"/"reserva"/"investimento", or the emergency reserve being "whichever box is
named Reserva de Emergência") has been replaced by an explicit flag
(`Category.reverse_logic`, `SavingsBox.is_emergency_reserve`). If you add a new
feature that needs to special-case a category or box, add a flag — don't match text.

---

## Pages & Features

- **Dashboard** (`/`, `dashboard.py`): month-scoped (navigate via `?mes=&ano=`, wraps
  across year boundaries). Shows balance cards (different sets for past/current/
  future), a "Contas do Mês" bill list, a compact per-card "Fatura do Cartão" summary
  (opens a detail modal broken down by card), and a "Movimentações de {mês}" feed
  (last 5 income+expense entries for the month being viewed).
- **Extrato** (`/extrato/`, `transactions.py: statement`): every movement, grouped by
  month (collapsible — only the current month, or the one matching an active filter,
  starts expanded), filterable by month/year (dropdowns) and free-text description
  search.
- **Caixinhas** (`/caixinhas/`, `savings_boxes.py`): list of boxes with quick balance
  sync, 30-day/12-month real yield; click through to a box's detail panel (see
  [Yield tracking](#savings-box-yield-tracking-not-a-cdi-projection)).
- **Análises** (`/relatorios/categorias/`, `reports.py: category_report`): 3-month
  "Semáforo" traffic light, budget-vs-actual per category, Custo Real / Aportes pizza
  charts, a Patrimônio (wealth) event chart, and an Emergency Reserve panel.
- **Visão Anual** (`/relatorios/anual/`, `reports.py: annual_report`): 12-card grid,
  one per month, reusing the same `_build_month_rows()` helper the Semáforo uses, so
  the two screens can never disagree about a given month's numbers.
- **Simulador de Compra Parcelada** (`/analise-anual/`, `annual_analysis.py`): 12-month
  cash-flow projection with an optional "what if I bought X in N installments"
  overlay. "Saldo Final" always reflects the simulated purchase (positive or
  negative); a month is only highlighted red if the simulated purchase actually tips
  it negative.
- **Planejamento / Categorias** (`/categorias/`): budget caps per category.
- **Cartões / Gastos Fixos / Receitas Fixas**: CRUD screens for the recurring
  templates.

## Shared UI Infrastructure

- **`finance/context_processors.py: quick_add_forms`**: registered in
  `core/settings.py`'s `TEMPLATES.OPTIONS.context_processors`, so every template render
  (not just specific views) gets:
  - `navbar_expense_form` / `navbar_income_form`: fresh `TransactionForm`/`IncomeForm`
    instances with a distinct `auto_id` prefix (`navbar_expense_%s` /
    `navbar_income_%s`), used by the "+ Despesa"/"+ Receita" quick-add modals in
    `base.html`. The distinct prefix matters: without it, a page that also renders the
    same form standalone (e.g. `/despesa/nova/`) would end up with two DOM elements
    sharing the same `id`.
  - `category_reverse_logic_json`: a `{category_id: bool}` map, dumped as JSON and
    read into the `categoryReverseLogicMap` JS global in `base.html`.
- **`base.html`'s inline `<script>`** exposes two reusable wiring functions, called
  once per form-id-prefix that needs them:
  - `wireUpCaixinhaDestino(prefix)`: shows the "Caixinha de Destino" field only when
    the selected category's `reverse_logic` is true (via `categoryReverseLogicMap`,
    not by parsing the category's label).
  - `wireUpCartaoToggle(prefix)`: shows the "Cartão"/"Parcelas" fields only when
    "Pagar com Cartão de Crédito?" is checked.

  Both are called for the navbar's `navbar_expense_` prefixed modal form; the
  standalone `/despesa/nova/` page uses Django's default `id_` prefix and has its own
  richer script (in `generic_form.html`) for the credit-card case specifically,
  because that page also does live parcela-amount ⇄ total-amount math that the
  quick-add modal deliberately does not replicate (kept simple on purpose).
- **`.toggle-card` CSS** (defined in both `base.html` and `generic_form.html`): the
  boolean-switch styling used everywhere a `BooleanField` needs a Bootstrap "switch"
  look instead of a plain checkbox. `BootstrapModelForm.__init__` (in `forms.py`)
  auto-applies `role="switch"` to every `CheckboxInput` widget, so a new boolean field
  gets the correct switch styling without any per-field configuration.
- **Toasts**: `messages.success(...)` calls (Django's messages framework) render as
  auto-dismissing Bootstrap toasts via a block in `base.html` — used after adding a
  transaction/income, paying invoices, resgates, and editing installment-group values.

## Migrations

`finance/migrations/` is **gitignored** — there's no migration history in version
control. This means:
- A fresh clone must run `python manage.py migrate` to build the schema from nothing;
  there's no seed/fixture data.
- Every schema change made during development in this environment needed its own
  migration generated and applied locally (`makemigrations` + `migrate`) since there's
  no history to fall back on.
- Several migrations in this app's history are **data backfills** (`RunPython`), not
  just schema changes — e.g. inferring `installment_group` from old `"(i/N)"` title
  suffixes, or computing `initial_balance` for existing savings boxes from their
  transaction history. These are one-time, "make historical data consistent with a
  newly-added flag" migrations; the *running app* never repeats that inference logic
  itself once the migration has run.

## Known Limitations

- **`SavingsBox.created_at`** was backfilled to "now" for boxes that existed before
  the field was added — their true creation date is unrecoverable, so age-dependent
  numbers (12-month yield window, goal-forecast pace) will be most accurate for boxes
  created after this field existed.
- **`create_card_notice.html`** is an orphaned template — no view renders it anymore
  (found during a UI audit). Harmless to leave, but not wired to any URL.
- **`SelfLoan`** ("Auto-Empréstimo") is a lower-traffic feature that hasn't received
  the same iteration/bug-fixing attention as the rest of the app.
- No automated test suite exists yet — verification throughout development has been
  manual, via `python manage.py check` plus ad hoc `django.test.Client` requests run
  through `manage.py shell`.
