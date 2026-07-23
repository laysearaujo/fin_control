from django.shortcuts import render, get_object_or_404
from django.db.models import Sum
from django.utils import timezone
from datetime import date
from dateutil.relativedelta import relativedelta

from ..models import Category, FixedIncome, FixedExpense, Transaction, Installment, Income, SavingsBox, OneOffBill


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
    # 1. INTERNAL FUNCTION TO COMPUTE A SINGLE MONTH
    # ==========================================
    def compute_month_data(m, y):
        # Checks whether the month has any real activity (debit or card)
        has_real_activity = Transaction.objects.filter(
            purchase_date__month=m, purchase_date__year=y
        ).exists() or Installment.objects.filter(
            due_date__month=m, due_date__year=y
        ).exists()

        debit_total = Transaction.objects.filter(
            is_credit_card=False, is_invoice_payment=False, is_internal_transfer=False, purchase_date__month=m, purchase_date__year=y
        ).aggregate(t=Sum('total_amount'))['t'] or 0.0

        installments_total = Installment.objects.filter(
            due_date__month=m, due_date__year=y
        ).aggregate(t=Sum('amount'))['t'] or 0.0

        # ONLY adds fixed expenses if the month has real activity!
        # This prevents subscriptions from leaking into past months where the app wasn't in use yet.
        if has_real_activity:
            fixed_total = FixedExpense.objects.filter(is_credit_card=True).aggregate(t=Sum('expected_amount'))['t'] or 0.0
        else:
            fixed_total = 0.0

        grand_total = float(debit_total) + float(installments_total) + float(fixed_total)

        # Filters this month's deposits
        deposits = 0.0
        if has_real_activity:
            debit_entries = Transaction.objects.filter(
                is_credit_card=False, is_invoice_payment=False, is_internal_transfer=False, purchase_date__month=m, purchase_date__year=y
            ).select_related('category')

            installment_entries = Installment.objects.filter(
                due_date__month=m, due_date__year=y
            ).select_related('transaction__category')

            fixed_entries = FixedExpense.objects.filter(is_credit_card=True).select_related('category')

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

    # ==========================================
    # 2. SELECTED MONTH'S DATA (PIE CHART AND DEPOSITS)
    # ==========================================
    debit_expenses = Transaction.objects.filter(
        is_credit_card=False, is_invoice_payment=False, is_internal_transfer=False, purchase_date__month=month, purchase_date__year=year
    ).values('category__id', 'category__name', 'category__reverse_logic').annotate(total=Sum('total_amount'))

    installments = Installment.objects.filter(
        due_date__month=month, due_date__year=year
    ).select_related('transaction__category')

    card_fixed_expenses = FixedExpense.objects.filter(is_credit_card=True).select_related('category')

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
    month_grand_total, month_deposits_total, month_actual_cost = compute_month_data(month, year)

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

    for i in range(5, -1, -1):
        month_date = ref_date - relativedelta(months=i)
        history_labels.append(month_date.strftime('%b/%y'))

        _, _, month_actual_cost_i = compute_month_data(month_date.month, month_date.year)

        # Only counts towards the average's divisor if there was real living cost that month
        if month_actual_cost_i > 0:
            months_with_real_spend += 1
            sum_real_cost_history += month_actual_cost_i

        total_income_i = Income.objects.filter(
            date__month=month_date.month, date__year=month_date.year
        ).aggregate(total=Sum('amount'))['total'] or 0.0
        history_income.append(float(total_income_i))
        history_expenses.append(month_actual_cost_i)

    # Dynamic average based only on months with real activity
    average_divisor = months_with_real_spend if months_with_real_spend > 0 else 1
    average_living_cost = sum_real_cost_history / average_divisor

    if average_living_cost == 0:
        average_living_cost = month_actual_cost

    # Calibrated goals (3 months minimum, 6 months ideal)
    minimum_reserve = average_living_cost * 3
    ideal_reserve = average_living_cost * 6

    # Looks up whichever savings box the user marked as their emergency reserve
    emergency_box = SavingsBox.objects.filter(is_emergency_reserve=True).first()

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

    traffic_light_data = []

    # Fetches the total fixed income registered in the system to use as a forecast
    total_recurring_fixed_income = float(FixedIncome.objects.aggregate(t=Sum('amount'))['t'] or 0.0)

    for month_ref in traffic_light_months:
        month_total, month_deposits, month_cost = compute_month_data(month_ref.month, month_ref.year)

        # Fetches what was actually deposited that month
        posted_total = Income.objects.filter(date__month=month_ref.month, date__year=month_ref.year).aggregate(t=Sum('amount'))['t'] or 0.0
        month_income = float(posted_total)

        # If it's a future month and it's still zero, assumes the expected fixed income
        if month_income == 0.0 and (month_ref.year > today.year or (month_ref.year == today.year and month_ref.month > today.month)):
            month_income = total_recurring_fixed_income

        real_leftover = month_income - month_total

        if real_leftover < 0:
            status = "Déficit ⚠️"
            color = "text-danger fw-bold"
        elif month_total == 0 and month_income == 0:
            status = "Sem lançamentos"
            color = "text-muted"
        else:
            status = "Saudável 🎯"
            color = "text-success fw-bold"

        traffic_light_data.append({
            'label': month_ref.strftime('%B / %Y'),
            'mes': month_ref.month,
            'ano': month_ref.year,
            'income': month_income,
            'actual_cost': month_cost,
            'deposits': month_deposits,
            'leftover': real_leftover,
            'status': status,
            'color': color
        })

    context = {
        'mes': month, 'ano': year, 'ref_date': ref_date,
        'prev_month_url': f"?mes={previous_month_url.month}&ano={previous_month_url.year}",
        'next_month_url': f"?mes={next_month_url.month}&ano={next_month_url.year}",
        'labels': expense_labels,
        'data': expense_values,
        'category_ids': expense_ids,
        'deposit_labels': deposit_labels,
        'deposit_values': deposit_values,
        'month_actual_cost': month_actual_cost,
        'total_deposits': month_deposits_total,
        'grand_total': month_grand_total,
        'history_labels': history_labels,
        'history_income': history_income,
        'history_expenses': history_expenses,
        'average_living_cost': average_living_cost,
        'minimum_reserve': minimum_reserve,
        'ideal_reserve': ideal_reserve,
        'reserve_balance': real_reserve_balance,
        'reserve_progress': reserve_progress,
        'traffic_light_data': traffic_light_data
    }
    return render(request, 'category_report.html', context)


def annual_report(request):
    """Builds the traffic light projecting how the month SHOULD end"""
    year = int(request.GET.get('ano', timezone.now().year))
    today = timezone.now().date()
    current_month = today.month
    current_year = today.year

    months_grid = []

    # Overall planning figures
    total_fixed_income = FixedIncome.objects.aggregate(Sum('amount'))['amount__sum'] or 0
    total_fixed_expense = FixedExpense.objects.aggregate(Sum('expected_amount'))['expected_amount__sum'] or 0

    # 1. Grabs the real balance from the last day of the previous year (base for the calculation)
    historical_income = Income.objects.filter(date__lt=date(year, 1, 1)).aggregate(Sum('amount'))['amount__sum'] or 0
    historical_expenses = Transaction.objects.filter(is_credit_card=False, is_internal_transfer=False, purchase_date__lt=date(year, 1, 1)).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    accumulated_balance = historical_income - historical_expenses

    for i in range(1, 13):
        ref_date = date(year, i, 1)

        # Is this month in the past? (e.g. we're in May and the loop is at March)
        is_past = year < current_year or (year == current_year and i < current_month)

        if is_past:
            # PAST MONTHS: exact real balance pinned to the last day of the month
            cutoff_date = ref_date + relativedelta(months=1)
            total_income = Income.objects.filter(date__lt=cutoff_date).aggregate(Sum('amount'))['amount__sum'] or 0
            total_expenses = Transaction.objects.filter(is_credit_card=False, is_internal_transfer=False, purchase_date__lt=cutoff_date).aggregate(Sum('total_amount'))['total_amount__sum'] or 0

            balance = total_income - total_expenses
            accumulated_balance = balance  # Updates the real snowball

        else:
            # CURRENT AND FUTURE MONTHS: projection of how the month WILL close
            # A. Projected income (if extra money already came in, uses the larger value)
            actual_income = Income.objects.filter(date__month=i, date__year=year).aggregate(Sum('amount'))['amount__sum'] or 0
            projected_income = max(total_fixed_income, actual_income)

            # B. Projected expenses (sums fixed commitments, card and one-off bills)
            installments = Installment.objects.filter(due_date__month=i, due_date__year=year).aggregate(Sum('amount'))['amount__sum'] or 0
            bills = OneOffBill.objects.filter(due_date__month=i, due_date__year=year).aggregate(Sum('amount'))['amount__sum'] or 0

            # Also grabs debit spending you already made (e.g. groceries) so it's not ignored
            extra_debit_expenses = Transaction.objects.filter(
                is_credit_card=False,
                is_invoice_payment=False,
                is_internal_transfer=False,
                fixed_expense__isnull=True,   # Skips fixed expenses (avoids double-counting)
                one_off_bill__isnull=True,    # Skips one-off bills (avoids double-counting)
                purchase_date__month=i,
                purchase_date__year=year
            ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0

            projected_expenses = total_fixed_expense + installments + bills + extra_debit_expenses

            # C. Closing math
            balance = accumulated_balance + projected_income - projected_expenses
            accumulated_balance = balance  # Updates the projected snowball for the next month

        months_grid.append({
            'month_num': i,
            'month_name': ref_date.strftime('%B'),
            'balance': balance,
            'color': 'success' if balance >= 0 else 'danger',
            'is_past': is_past
        })

    return render(request, 'annual_report.html', {'ano': year, 'grid': months_grid})


def category_expense_detail(request, categoria_id):
    """Shows the full, category-exclusive expense listing ordered from most to least expensive"""
    category = get_object_or_404(Category, id=categoria_id)
    month = int(request.GET.get('mes', timezone.now().month))
    year = int(request.GET.get('ano', timezone.now().year))

    expense_details = []

    # 1. Debit / cash
    debit_transactions = Transaction.objects.filter(
        category=category,
        is_credit_card=False,
        is_invoice_payment=False,
        is_internal_transfer=False,
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
        category=category, is_credit_card=True, due_day__gt=0  # Just to simulate the date
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
