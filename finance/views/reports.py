import json

from django.shortcuts import render
from django.db.models import Sum, Q
from django.utils import timezone
from datetime import date
from dateutil.relativedelta import relativedelta

from ..models import Category, FixedIncome, FixedExpense, Transaction, Installment, Income, SavingsBox, OneOffBill
from .categories import _count_pending_categorization
from ._helpers import get_owned_or_404

# Python's strftime('%B')/('%b') depends on the OS locale being installed, which isn't reliable
# in every environment — so month names are spelled out by hand instead.
MESES_PT = {
    1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril', 5: 'Maio', 6: 'Junho',
    7: 'Julho', 8: 'Agosto', 9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro',
}
MESES_PT_ABREV = {
    1: 'Jan', 2: 'Fev', 3: 'Mar', 4: 'Abr', 5: 'Mai', 6: 'Jun',
    7: 'Jul', 8: 'Ago', 9: 'Set', 10: 'Out', 11: 'Nov', 12: 'Dez',
}


def compute_month_data(user, m, y):
    """Computes a single month's total spend, deposits and actual cost of living.

    Shared by category_report (3-month traffic light) and annual_report (12-month grid) so
    both screens always agree on what a given month's numbers are.
    """
    # Checks whether the month has any real activity (debit or card)
    has_real_activity = Transaction.objects.filter(
        owner=user, purchase_date__month=m, purchase_date__year=y
    ).exists() or Installment.objects.filter(
        transaction__owner=user, due_date__month=m, due_date__year=y
    ).exists()

    # Includes savings-box withdrawals: that money was genuinely spent on something real,
    # it just came from a caixinha instead of the checking account (only the Dashboard's
    # balance calculation needs to ignore it, not the spend-by-category analysis here)
    debit_total = Transaction.objects.filter(
        owner=user, is_credit_card=False, is_invoice_payment=False, purchase_date__month=m, purchase_date__year=y
    ).aggregate(t=Sum('total_amount'))['t'] or 0.0

    installments_total = Installment.objects.filter(
        transaction__owner=user, due_date__month=m, due_date__year=y
    ).aggregate(t=Sum('amount'))['t'] or 0.0

    # ONLY adds fixed expenses if the month has real activity!
    # This prevents subscriptions from leaking into past months where the app wasn't in use yet.
    if has_real_activity:
        fixed_total = FixedExpense.objects.filter(owner=user, is_credit_card=True).aggregate(t=Sum('expected_amount'))['t'] or 0.0
    else:
        fixed_total = 0.0

    grand_total = float(debit_total) + float(installments_total) + float(fixed_total)

    # Filters this month's deposits
    deposits = 0.0
    if has_real_activity:
        debit_entries = Transaction.objects.filter(
            owner=user, is_credit_card=False, is_invoice_payment=False, purchase_date__month=m, purchase_date__year=y
        ).select_related('category')

        installment_entries = Installment.objects.filter(
            transaction__owner=user, due_date__month=m, due_date__year=y
        ).select_related('transaction__category')

        fixed_entries = FixedExpense.objects.filter(owner=user, is_credit_card=True).select_related('category')

        for entry in debit_entries:
            if entry.category and entry.category.reverse_logic:
                deposits += float(entry.total_amount or 0)

        for entry in installment_entries:
            category = entry.transaction.category
            if category and category.reverse_logic:
                deposits += float(entry.amount or 0)

        for entry in fixed_entries:
            if entry.category and entry.category.reverse_logic:
                deposits += float(entry.expected_amount or 0)

    actual_cost = grand_total - deposits
    return grand_total, deposits, actual_cost


def _month_status(month_income, month_total, leftover):
    """Same Déficit/Saudável/Sem lançamentos classification used across the traffic lights"""
    if leftover < 0:
        return "Déficit ⚠️", "text-danger fw-bold"
    if month_total == 0 and month_income == 0:
        return "Sem lançamentos", "text-muted"
    return "Saudável 🎯", "text-success fw-bold"


def _checking_balance_before(user, cutoff_date):
    """Real checking-account balance carried over from before cutoff_date (same accounting
    rule as the Dashboard: a savings-box withdrawal doesn't move this balance)."""
    income_before = Income.objects.filter(owner=user, date__lt=cutoff_date).aggregate(Sum('amount'))['amount__sum'] or 0
    expenses_before = Transaction.objects.filter(
        owner=user, is_credit_card=False, is_internal_transfer=False, purchase_date__lt=cutoff_date
    ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    return float(income_before) - float(expenses_before)


def _build_month_rows(user, months, starting_balance, today, total_recurring_fixed_income):
    """Builds one row per (month, year) in `months`, carrying the running balance across them
    in order so "saldo anterior + entradas - custo real - aportes = saldo final" always holds.
    Shared by the 3-month traffic light (category_report) and the 12-month grid (annual_report)
    so the two screens can never show different numbers for the same month.
    """
    rows = []
    running_balance = starting_balance

    for month_ref in months:
        month_total, month_deposits, month_cost = compute_month_data(user, month_ref.month, month_ref.year)

        is_current_or_future_month = month_ref.year > today.year or (month_ref.year == today.year and month_ref.month >= today.month)

        # For the current/future month, forecasts non-card fixed expenses that haven't
        # posted yet (e.g. the recurring R$2000 aporte due on day 5) - same idea as the
        # income forecast right below, and matches the Dashboard's own balance projection.
        if is_current_or_future_month:
            bank_fixed_expenses = FixedExpense.objects.filter(owner=user, is_credit_card=False).select_related('category')
            for expense in bank_fixed_expenses:
                already_paid = Transaction.objects.filter(
                    owner=user, fixed_expense=expense, purchase_date__month=month_ref.month, purchase_date__year=month_ref.year
                ).exists()
                if not already_paid:
                    amount = float(expense.expected_amount)
                    month_total += amount
                    if expense.category and expense.category.reverse_logic:
                        month_deposits += amount
            month_cost = month_total - month_deposits

        posted_total = Income.objects.filter(owner=user, date__month=month_ref.month, date__year=month_ref.year).aggregate(t=Sum('amount'))['t'] or 0.0
        month_income = float(posted_total)

        # If it's the current month or a future one and nothing's posted yet, assumes the
        # expected fixed income - matches the Dashboard, which forecasts this month's salary
        # the same way as long as it hasn't actually been received yet (e.g. salary lands on
        # day 27, so day 1 of the current month legitimately has R$0 posted so far)
        if month_income == 0.0 and is_current_or_future_month:
            month_income = total_recurring_fixed_income

        # Status reflects THIS month alone (income vs. cost), not the running balance
        monthly_net = month_income - month_total
        status, status_color = _month_status(month_income, month_total, monthly_net)

        # month_cost (custo real) intentionally INCLUDES savings-box withdrawals — that money
        # was really spent on something, so it belongs in the category/spend analysis. But a
        # resgate never actually left the checking account (it came from the caixinha), so it
        # must NOT be subtracted again here — otherwise the projected balance drifts away from
        # what the account really has. We back it out so "saldo anterior + entradas - custo
        # real - aportes = saldo final" reconciles to the real, verifiable account balance.
        month_resgates = float(Transaction.objects.filter(
            owner=user, is_internal_transfer=True, purchase_date__month=month_ref.month, purchase_date__year=month_ref.year
        ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0)
        balance_cost = month_cost - month_resgates

        previous_balance = running_balance
        ending_balance = previous_balance + month_income - balance_cost - month_deposits
        running_balance = ending_balance

        rows.append({
            'month_ref': month_ref,
            'income': month_income,
            'cost': balance_cost,
            'deposits': month_deposits,
            'resgates': month_resgates,
            'previous_balance': previous_balance,
            'ending_balance': ending_balance,
            'status': status,
            'status_color': status_color,
        })

    return rows


def category_report(request):
    """Builds the single strategic-analysis screen with multiple charts and the 3-month traffic light"""
    month_url = request.GET.get('mes')
    year_url = request.GET.get('ano')
    today = timezone.now().date()

    try:
        if month_url and year_url:
            month = int(month_url)
            year = int(year_url)
            if month > 12:
                month = 1
                year += 1
            elif month < 1:
                month = 12
                year -= 1
            ref_date = date(year, month, 1)
        else:
            month = today.month
            year = today.year
            ref_date = date(year, month, 1)
    except (ValueError, TypeError):
        month = today.month
        year = today.year
        ref_date = date(year, month, 1)

    previous_month_url = ref_date - relativedelta(months=1)
    next_month_url = ref_date + relativedelta(months=1)

    # ==========================================
    # 2. SELECTED MONTH'S DATA (PIE CHART AND DEPOSITS)
    # ==========================================
    debit_expenses = Transaction.objects.filter(
        owner=request.user, is_credit_card=False, is_invoice_payment=False, purchase_date__month=month, purchase_date__year=year
    ).values('category__id', 'category__name', 'category__reverse_logic').annotate(total=Sum('total_amount'))

    installments = Installment.objects.filter(
        transaction__owner=request.user, due_date__month=month, due_date__year=year
    ).select_related('transaction__category')

    card_fixed_expenses = FixedExpense.objects.filter(owner=request.user, is_credit_card=True).select_related('category')

    NO_CATEGORY_LABEL = 'Sem Categoria'
    totals_by_category = {}

    for entry in debit_expenses:
        name = entry['category__name'] or NO_CATEGORY_LABEL
        category_id = entry['category__id'] or None
        is_deposit = bool(entry['category__reverse_logic'])
        if name not in totals_by_category: totals_by_category[name] = [0.0, category_id, is_deposit]
        totals_by_category[name][0] += float(entry['total'] or 0)

    for installment in installments:
        category = installment.transaction.category
        name = category.name if category else NO_CATEGORY_LABEL
        if name not in totals_by_category: totals_by_category[name] = [0.0, category.id if category else None, bool(category and category.reverse_logic)]
        totals_by_category[name][0] += float(installment.amount or 0)

    for expense in card_fixed_expenses:
        name = expense.category.name if expense.category else NO_CATEGORY_LABEL
        if name not in totals_by_category: totals_by_category[name] = [0.0, expense.category.id if expense.category else None, bool(expense.category and expense.category.reverse_logic)]
        totals_by_category[name][0] += float(expense.expected_amount or 0)

    # Splits pure expenses from investments for the two pie charts
    month_grand_total, month_deposits_total, month_actual_cost = compute_month_data(request.user, month, year)

    # How much of what you received this month went into deposits/savings
    month_income_total = float(Income.objects.filter(owner=request.user, date__month=month, date__year=year).aggregate(Sum('amount'))['amount__sum'] or 0)
    deposits_pct_of_income = (month_deposits_total / month_income_total * 100) if month_income_total > 0 else 0

    # Sorts the dict by value descending so the side list looks nice
    sorted_data = sorted(totals_by_category.items(), key=lambda item: item[1][0], reverse=True)

    expense_labels = []
    expense_values = []
    expense_ids = []

    deposit_labels = []
    deposit_values = []

    for name, data in sorted_data:
        _, category_id, is_deposit = data
        if is_deposit:
            deposit_labels.append(name)
            deposit_values.append(data[0])
        else:
            expense_labels.append(name)
            expense_values.append(data[0])
            expense_ids.append(category_id)

    # ==========================================
    # 3. HISTORY AND SMART AVERAGE CALCULATION
    # ==========================================
    history_labels = []
    history_income = []
    history_expenses = []

    months_with_real_spend = 0
    sum_real_cost_history = 0.0

    # Checking-account balance carried over from before the 6-month window starts, so the first
    # month's "available income" already accounts for what was left over from earlier months
    window_start_date = ref_date - relativedelta(months=5)
    running_checking_balance = float(Income.objects.filter(owner=request.user, date__lt=window_start_date).aggregate(Sum('amount'))['amount__sum'] or 0) - float(
        Transaction.objects.filter(owner=request.user, is_credit_card=False, is_internal_transfer=False, purchase_date__lt=window_start_date).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    )

    for i in range(5, -1, -1):
        month_date = ref_date - relativedelta(months=i)
        history_labels.append(f"{MESES_PT_ABREV[month_date.month]}/{month_date.strftime('%y')}")

        month_grand_total_i, _, month_actual_cost_i = compute_month_data(request.user, month_date.month, month_date.year)

        # The current calendar month is still in progress - averaging it in as if it were a
        # complete month would understate the real cost of living (e.g. viewing this on day 1
        # would count a near-empty month and drag the average, and the suggested reserve, down)
        is_still_in_progress = month_date.year == today.year and month_date.month == today.month

        # Only counts towards the average's divisor if there was real living cost that month
        if month_actual_cost_i > 0 and not is_still_in_progress:
            months_with_real_spend += 1
            sum_real_cost_history += month_actual_cost_i

        total_income_i = Income.objects.filter(
            owner=request.user, date__month=month_date.month, date__year=month_date.year
        ).aggregate(total=Sum('amount'))['total'] or 0.0

        # "Available this month" = what was left over from the previous month + what came in now —
        # this is the amount you actually started the month with, not just the raw salary
        available_income_i = running_checking_balance + float(total_income_i)
        history_income.append(available_income_i)

        # Rolls the checking balance forward for next month's carryover (excludes savings-box
        # withdrawals, same rule as the Dashboard: a resgate doesn't move the checking balance)
        month_checking_expense_i = float(Transaction.objects.filter(
            owner=request.user, is_credit_card=False, is_internal_transfer=False, purchase_date__month=month_date.month, purchase_date__year=month_date.year
        ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0)
        running_checking_balance = available_income_i - month_checking_expense_i

        # Uses the grand total (custo real + aportes), not just custo real: an aporte is money
        # that really left the checking account too, so "saídas reais" should include it here.
        # (average_living_cost below still uses actual_cost, excluding aportes on purpose —
        # that one measures cost of living for the emergency-reserve target, a different thing.)
        history_expenses.append(month_grand_total_i)

    # Dynamic average based only on months with real activity
    average_divisor = months_with_real_spend if months_with_real_spend > 0 else 1
    average_living_cost = sum_real_cost_history / average_divisor

    # Builds the wealth (patrimônio) timeline event by event (not smoothed by month), so the
    # line actually rises on each deposit and drops on each withdrawal. Anchored on today's real
    # total and walked backwards so the last point always matches the current balance exactly.
    current_total_wealth = float(SavingsBox.objects.for_user(request.user).aggregate(Sum('current_balance'))['current_balance__sum'] or 0)
    wealth_movements = Transaction.objects.filter(
        Q(owner=request.user), Q(target_savings_box__isnull=False) | Q(source_savings_box__isnull=False)
    ).order_by('purchase_date', 'id')

    net_total_movements = 0.0
    movement_events = []
    for movement in wealth_movements:
        amount = float(movement.total_amount)
        change = amount if movement.target_savings_box_id else -amount
        net_total_movements += change
        movement_events.append((movement, change))

    wealth_labels = ['Início']
    wealth_history = [current_total_wealth - net_total_movements]
    running_wealth = wealth_history[0]
    for movement, change in movement_events:
        running_wealth += change
        wealth_labels.append(movement.purchase_date.strftime('%d/%m/%y'))
        wealth_history.append(running_wealth)

    if average_living_cost == 0:
        average_living_cost = month_actual_cost

    # Calibrated goals (3 months minimum, 6 months ideal)
    minimum_reserve = average_living_cost * 3
    ideal_reserve = average_living_cost * 6

    # Looks up whichever savings box the user marked as their emergency reserve
    emergency_box = SavingsBox.objects.for_user(request.user).filter(is_emergency_reserve=True).first()

    # If the box exists, grabs its balance. If not (or it's empty), assumes 0.0
    real_reserve_balance = float(emergency_box.current_balance) if emergency_box else 0.0

    # Progress is now based on the actual emergency-fund money
    reserve_progress = min(int((real_reserve_balance / ideal_reserve) * 100), 100) if ideal_reserve > 0 else 0

    # ==========================================
    # 4. 3-MONTH TRAFFIC LIGHT ASSEMBLY
    # ==========================================
    traffic_light_months = [
        ref_date - relativedelta(months=1),  # Previous
        ref_date,                            # Current
        ref_date + relativedelta(months=1)   # Next
    ]

    # Fetches the total fixed income registered in the system to use as a forecast
    total_recurring_fixed_income = float(FixedIncome.objects.for_user(request.user).aggregate(t=Sum('amount'))['t'] or 0.0)

    # Same shared month-by-month builder the 12-month Visão Anual uses, carrying the running
    # balance from before the "previous month" so the numbers always reconcile between screens
    starting_balance = _checking_balance_before(request.user, date(traffic_light_months[0].year, traffic_light_months[0].month, 1))
    month_rows = _build_month_rows(request.user, traffic_light_months, starting_balance, today, total_recurring_fixed_income)

    traffic_light_data = []
    for row in month_rows:
        bg_color, text_color = _STATUS_CARD_COLORS[row['status']]
        traffic_light_data.append({
            'label': f"{MESES_PT[row['month_ref'].month]} / {row['month_ref'].year}",
            'mes': row['month_ref'].month,
            'ano': row['month_ref'].year,
            'previous_balance': row['previous_balance'],
            'income': row['income'],
            'actual_cost': row['cost'],
            'deposits': row['deposits'],
            'resgates': row['resgates'],
            'leftover': row['ending_balance'],
            'status': row['status'],
            'color': row['status_color'],
            'bg_color': bg_color,
            'text_color': text_color,
        })

    # Quick budget-planning summary card (mirrors manage_categories's totals for this month,
    # so the numbers always match the full Planejamento screen)
    total_planned = Category.objects.for_user(request.user).aggregate(Sum('monthly_cap'))['monthly_cap__sum'] or 0
    # Excludes is_invoice_payment=True: that's just the lump-sum settlement of the card charges
    # already counted below via installments/card-fixed-expenses — counting both double-counts it
    planned_debit_spend = Transaction.objects.filter(
        owner=request.user, is_credit_card=False, is_invoice_payment=False, purchase_date__month=month, purchase_date__year=year
    ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    planned_card_spend = Installment.objects.filter(
        transaction__owner=request.user, due_date__month=month, due_date__year=year
    ).aggregate(Sum('amount'))['amount__sum'] or 0
    planned_card_fixed_spend = FixedExpense.objects.filter(
        owner=request.user, is_credit_card=True
    ).aggregate(Sum('expected_amount'))['expected_amount__sum'] or 0
    total_planned_spent = planned_debit_spend + planned_card_spend + planned_card_fixed_spend
    planned_leftover = total_planned - total_planned_spent

    context = {
        'mes': month, 'ano': year, 'ref_date': ref_date,
        'prev_month_url': f"?mes={previous_month_url.month}&ano={previous_month_url.year}",
        'next_month_url': f"?mes={next_month_url.month}&ano={next_month_url.year}",
        'labels': expense_labels,
        'data': expense_values,
        # json.dumps (not the raw list) so an uncategorized transaction's None becomes
        # the valid JS token "null" instead of the literal text "None" - the latter is
        # a JS ReferenceError that silently kills the whole chart-building script,
        # which is why a month with zero uncategorized spend rendered fine while one
        # with any "Sem Categoria" transaction showed every chart on the page blank.
        'category_ids': json.dumps(expense_ids),
        'deposit_labels': deposit_labels,
        'deposit_values': deposit_values,
        'month_actual_cost': month_actual_cost,
        'total_deposits': month_deposits_total,
        'deposits_pct_of_income': deposits_pct_of_income,
        'grand_total': month_grand_total,
        'history_labels': history_labels,
        'history_income': history_income,
        'history_expenses': history_expenses,
        'wealth_labels': wealth_labels,
        'wealth_history': wealth_history,
        'total_wealth': current_total_wealth,
        'average_living_cost': average_living_cost,
        'minimum_reserve': minimum_reserve,
        'ideal_reserve': ideal_reserve,
        'reserve_balance': real_reserve_balance,
        'reserve_progress': reserve_progress,
        'emergency_box_id': emergency_box.id if emergency_box else None,
        'traffic_light_data': traffic_light_data,
        'total_planned': total_planned,
        'total_planned_spent': total_planned_spent,
        'planned_leftover': planned_leftover,
        'total_pending_categorization': _count_pending_categorization(request.user),
    }
    return render(request, 'category_report.html', context)


_STATUS_CARD_COLORS = {
    "Déficit ⚠️": ('#f8d7da', '#842029'),
    "Sem lançamentos": ('#e9ecef', '#495057'),
    "Saudável 🎯": ('#d1e7dd', '#0f5132'),
}


def annual_report(request):
    """Builds the traffic light for the whole year, using the same shared month-by-month
    builder as the Análises 3-month traffic light, so the two screens never disagree."""
    year = int(request.GET.get('ano', timezone.now().year))
    today = timezone.now().date()

    total_recurring_fixed_income = float(FixedIncome.objects.for_user(request.user).aggregate(t=Sum('amount'))['t'] or 0.0)

    year_start = date(year, 1, 1)
    starting_balance = _checking_balance_before(request.user, year_start)
    months = [date(year, i, 1) for i in range(1, 13)]
    month_rows = _build_month_rows(request.user, months, starting_balance, today, total_recurring_fixed_income)

    months_grid = []
    for row in month_rows:
        ref_date = row['month_ref']
        bg_color, text_color = _STATUS_CARD_COLORS[row['status']]

        months_grid.append({
            'month_num': ref_date.month,
            'month_name': MESES_PT[ref_date.month],
            'previous_balance': row['previous_balance'],
            'income': row['income'],
            'cost': row['cost'],
            'deposits': row['deposits'],
            'resgates': row['resgates'],
            'ending_balance': row['ending_balance'],
            'status': row['status'],
            'status_color': row['status_color'],
            'bg_color': bg_color,
            'text_color': text_color,
            'is_past': ref_date < date(today.year, today.month, 1),
        })

    return render(request, 'annual_report.html', {'ano': year, 'grid': months_grid})


def category_expense_detail(request, categoria_id):
    """Shows the full, category-exclusive expense listing ordered from most to least expensive"""
    category = get_owned_or_404(request, Category, id=categoria_id)
    month = int(request.GET.get('mes', timezone.now().month))
    year = int(request.GET.get('ano', timezone.now().year))

    expense_details = []

    # 1. Debit / cash
    debit_transactions = Transaction.objects.filter(
        owner=request.user,
        category=category,
        is_credit_card=False,
        is_invoice_payment=False,
        purchase_date__month=month,
        purchase_date__year=year
    )
    for txn in debit_transactions:
        expense_details.append({
            'date': txn.purchase_date,
            'description': txn.description,
            'amount': float(txn.total_amount),
            'type': 'Débito / PIX'
        })

    # 2. Credit card installments
    card_installments = Installment.objects.filter(
        transaction__owner=request.user,
        transaction__category=category,
        due_date__month=month,
        due_date__year=year
    ).select_related('transaction')
    for installment in card_installments:
        expense_details.append({
            'date': installment.due_date,
            'description': f"{installment.transaction.description} ({installment.installment_number}/{installment.transaction.installments_count})",
            'amount': float(installment.amount),
            'type': 'Cartão de Crédito'
        })

    # 3. Fixed expenses / subscriptions on the card
    # Filters fixed expenses to the queried month/year so subscriptions from other
    # months don't leak into this breakdown.
    card_fixed_expenses = FixedExpense.objects.filter(
        owner=request.user, category=category, is_credit_card=True, due_day__gt=0  # Just to simulate the date
    )
    for expense in card_fixed_expenses:
        expense_details.append({
            # Makes sure the recurring expense's date respects the queried month/year.
            # min() avoids errors on months with fewer than 31 days.
            # relativedelta(day=expense.due_day) sets the correct day.
            'date': date(year, month, 1) + relativedelta(day=min(int(expense.due_day), 28)),
            'description': f"{expense.name} (Assinatura)",
            'amount': float(expense.expected_amount),
            'type': 'Cartão (Recorrente)'
        })

    # Sorts from most to least expensive
    expense_details.sort(key=lambda x: x['amount'], reverse=True)
    total_spent = sum(item['amount'] for item in expense_details)

    context = {
        'category': category,
        'expenses': expense_details,
        'total': total_spent,
        'mes': month,
        'ano': year,
    }
    return render(request, 'category_expense_detail.html', context)
