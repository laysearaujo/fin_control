*[Português](README.md) | English*

# 💰 Guardião - Personal Finance Management

Personal finance tracker built with Django. The project's focus is giving a clear
view of your real checking-account balance versus future forecasts, with separate
handling for credit cards (one or several), fixed/recurring bills, installment-split
one-off bills, and savings boxes with real (not projected) yield.

For technical architecture and business-rule details, see
[DOCUMENTATION.md](DOCUMENTATION.md).

## 🚀 Key Features

- **📊 Smart Dashboard:**
  - Time-travel view: navigate between Last Month (Historical), Current Month
    (Execution), and Future Months (Forecast).
  - Clear separation between "Checking Balance" and "Credit Card Invoice".
  - This month's bills (recurring + one-off) sorted by urgency, with a progress bar
    of how many are already paid.
  - A "Recent Movements" feed for the month, right on the home screen.
  - "+ Expense" and "+ Income" buttons open a quick-add modal from any page.

- **💳 Credit Cards (multiple):**
  - Supports more than one card, each with its own closing/due day and its own
    invoice — paying one card never affects another.
  - Expense entry with automatic installment splitting, aware of the card's closing
    date (a purchase made close to closing rolls into next month's invoice).
  - Recurring subscriptions (e.g. Netflix) automatically added to the invoice.
  - Per-card invoice breakdown, including how much is already accumulating for next
    month.

- **🐖 Savings Boxes ("Caixinhas"):**
  - Set money aside from your checking balance via deposits and withdrawals.
  - **Real** yield, calculated from your balance-sync history — no speculative rate
    projection. Shows yield over the last 30 days and the last 12 months (or since
    creation, if the box is younger than that).
  - Goal-completion forecast based on your actual growth pace.
  - An event-by-event balance chart (rises on every deposit, drops on every
    withdrawal).
  - "Self-loan" feature (borrow from a box, pay yourself back with interest).

- **📜 Statement ("Extrato"):**
  - Every movement grouped by month, each group collapsible (only the current month
    starts expanded).
  - Filter by month, year, and free-text description search.

- **📈 Analytics ("Análises"):**
  - A 3-month traffic light (green/yellow/red) to spot critical months.
  - Real Cost and Contribution Allocation charts.
  - A Net Worth (Patrimônio) chart showing savings boxes' evolution over time.
  - An Emergency Reserve panel.
  - An Annual View with all 12 months side by side.
  - Installment purchase simulator: see the impact of a new purchase on the next 12
    months' cash flow before committing to it.

- **📂 Planning:**
  - Monthly spending cap per category and how much has been spent/contributed in
    each.

## 🛠️ Tech Stack

- **Backend:** Python, Django 6.0
- **Database:** SQLite
- **Frontend:** HTML5, Bootstrap 5 (via CDN), vanilla JavaScript, Chart.js — no build
  step, no JS framework
- **Libraries:** `python-dateutil` (date math)

## ⚙️ Running Locally

1. **Clone the repository:**

   ```bash
   git clone https://github.com/YOUR_USERNAME/fin_control.git
   cd fin_control
   ```

2. **Create and activate a virtual environment:**

    ```bash
    python3 -m venv venv
    # On Windows:
    venv\Scripts\activate
    # On Mac/Linux:
    source venv/bin/activate
    ```

3. **Install dependencies:**

    ```bash
    pip install -r requirements.txt
    ```

4. **Set up the database:**

    ```bash
    python manage.py migrate
    ```

5. **Start the server:**

    ```bash
    python manage.py runserver
    ```

6. Open `http://127.0.0.1:8000/` in your browser.
