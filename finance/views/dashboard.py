from django.shortcuts import render
from django.db.models import Sum
from django.utils import timezone
from datetime import date
from dateutil.relativedelta import relativedelta

from ..models import Transaction, Income, FixedExpense, FixedIncome, Installment, SavingsBox, CreditCard, OneOffBill, Category


def dashboard(request):
    # --- DATE RESOLUTION ---
    month_url = request.GET.get('mes')
    year_url = request.GET.get('ano')
    today = timezone.now().date()

    try:
        if month_url and year_url:
            month_int = int(month_url)
            year_int = int(year_url)

            # Wraps around year boundaries (month 13 -> month 1 next year, month 0 -> month 12 previous year)
            if month_int > 12:
                month_int = 1
                year_int += 1
            elif month_int < 1:
                month_int = 12
                year_int -= 1

            ref_date = date(year_int, month_int, 1)
        else:
            ref_date = date(today.year, today.month, 1)

    except (ValueError, TypeError):
        # Falls back to the current month if the URL params are garbage/empty
        ref_date = date(today.year, today.month, 1)

    previous_month = ref_date - relativedelta(months=1)
    next_month = ref_date + relativedelta(months=1)

    current_month_start = date(today.year, today.month, 1)

    is_past = ref_date < current_month_start
    is_future = ref_date > current_month_start
    is_current = (ref_date == current_month_start)

    # =========================================================================
    # 1. BASE BALANCE CALCULATION (CURRENT MONTH FORECAST)
    # =========================================================================

    # A. Real balance TODAY
    income_today = Income.objects.filter(date__lte=today).aggregate(Sum('amount'))['amount__sum'] or 0
    expenses_today = Transaction.objects.filter(is_credit_card=False, is_internal_transfer=False, purchase_date__lte=today).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    base_balance = income_today - expenses_today

    # B. Pending items for the current month
    # Fixed income
    for fixed_income in FixedIncome.objects.all():
        already_received = Income.objects.filter(fixed_income=fixed_income, date__month=today.month, date__year=today.year).exists()
        if not already_received:
            base_balance += fixed_income.amount

    # Bank fixed expenses
    for expense in FixedExpense.objects.filter(is_credit_card=False):
        paid = Transaction.objects.filter(fixed_expense=expense, purchase_date__month=today.month, purchase_date__year=today.year).exists()
        if not paid:
            base_balance -= expense.expected_amount

    # One-off bills for the current month
    bills_today = OneOffBill.objects.filter(due_date__month=today.month, due_date__year=today.year)
    for bill in bills_today:
        paid = Transaction.objects.filter(one_off_bill=bill).exists()
        if not paid:
            base_balance -= bill.amount

    # Current month's credit card invoice
    if not Transaction.objects.filter(is_invoice_payment=True, invoice_month=today.month, invoice_year=today.year).exists():
        installments_sum = Installment.objects.filter(due_date__month=today.month, due_date__year=today.year).aggregate(Sum('amount'))['amount__sum'] or 0
        subscriptions_sum = 0
        for expense in FixedExpense.objects.filter(is_credit_card=True):
            if not Transaction.objects.filter(fixed_expense=expense, purchase_date__month=today.month, purchase_date__year=today.year).exists():
                subscriptions_sum += expense.expected_amount
        base_balance -= (installments_sum + subscriptions_sum)

    # =========================================================================
    # 2. PREVIOUS BALANCE (CASCADING LOOP)
    # =========================================================================

    if is_future:
        accumulated_balance = base_balance
        month_cursor = current_month_start + relativedelta(months=1)

        while month_cursor < ref_date:
            # Income
            month_income = FixedIncome.objects.aggregate(Sum('amount'))['amount__sum'] or 0

            # Fixed expenses
            month_bank_expenses = FixedExpense.objects.filter(is_credit_card=False).aggregate(Sum('expected_amount'))['expected_amount__sum'] or 0

            # One-off bills for the intermediate month
            month_bills = OneOffBill.objects.filter(due_date__month=month_cursor.month, due_date__year=month_cursor.year).aggregate(Sum('amount'))['amount__sum'] or 0

            # Estimated invoice
            month_installments = Installment.objects.filter(due_date__month=month_cursor.month, due_date__year=month_cursor.year).aggregate(Sum('amount'))['amount__sum'] or 0
            month_subscriptions = FixedExpense.objects.filter(is_credit_card=True).aggregate(Sum('expected_amount'))['expected_amount__sum'] or 0
            month_invoice = month_installments + month_subscriptions

            # Net balance for the month (including one-off bills)
            month_net_balance = month_income - (month_bank_expenses + month_bills + month_invoice)

            accumulated_balance += month_net_balance
            month_cursor += relativedelta(months=1)

        previous_balance = accumulated_balance

    else:
        historical_income = Income.objects.filter(date__lt=ref_date).aggregate(Sum('amount'))['amount__sum'] or 0
        historical_expenses = Transaction.objects.filter(is_credit_card=False, is_internal_transfer=False, purchase_date__lt=ref_date).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        previous_balance = historical_income - historical_expenses

    # =========================================================================
    # 3. SCREEN DATA
    # =========================================================================

    # Credit card invoice
    invoice_line_items = []
    invoice_installments = Installment.objects.filter(due_date__month=ref_date.month, due_date__year=ref_date.year).select_related('transaction')
    installments_total = invoice_installments.aggregate(Sum('amount'))['amount__sum'] or 0
    for installment in invoice_installments:
        invoice_line_items.append({'description': f"{installment.transaction.description} ({installment.installment_number}/{installment.transaction.installments_count})", 'amount': installment.amount, 'kind': 'purchase'})

    subscriptions_total = 0
    credit_card_fixed_expenses = FixedExpense.objects.filter(is_credit_card=True)
    for expense in credit_card_fixed_expenses:
        already_posted = Transaction.objects.filter(fixed_expense=expense, purchase_date__month=ref_date.month, purchase_date__year=ref_date.year).exists()
        if not already_posted:
            subscriptions_total += expense.expected_amount
            invoice_line_items.append({'description': f"{expense.name} (Assinatura)", 'amount': expense.expected_amount, 'kind': 'fixed'})

    month_invoice_total = installments_total + subscriptions_total

    # What's already accumulating for NEXT month's invoice (installments already scheduled +
    # subscriptions not yet posted), so purchases made today don't sneak up unnoticed
    next_invoice_month = ref_date + relativedelta(months=1)
    next_installments_total = Installment.objects.filter(due_date__month=next_invoice_month.month, due_date__year=next_invoice_month.year).aggregate(Sum('amount'))['amount__sum'] or 0
    next_subscriptions_total = 0
    for expense in credit_card_fixed_expenses:
        already_posted_next = Transaction.objects.filter(fixed_expense=expense, purchase_date__month=next_invoice_month.month, purchase_date__year=next_invoice_month.year).exists()
        if not already_posted_next:
            next_subscriptions_total += expense.expected_amount
    next_invoice_total = next_installments_total + next_subscriptions_total

    # The base forecast is just your fixed salary
    total_fixed_income = FixedIncome.objects.aggregate(Sum('amount'))['amount__sum'] or 0
    forecast_total_income = total_fixed_income

    # 1. Actual income (only what was really received and saved to the DB)
    month_actual_income = Income.objects.filter(date__month=ref_date.month, date__year=ref_date.year).aggregate(Sum('amount'))['amount__sum'] or 0

    # 2. Actual outflows
    month_actual_expenses = Transaction.objects.filter(is_credit_card=False, is_internal_transfer=False, purchase_date__month=ref_date.month, purchase_date__year=ref_date.year).aggregate(Sum('total_amount'))['total_amount__sum'] or 0

    # Adjusts the forecast in case you got extra money this month (beyond the fixed income)
    income_still_expected = forecast_total_income - month_actual_income
    if income_still_expected < 0:
        income_still_expected = 0
        forecast_total_income = month_actual_income  # The forecast adjusts to the positive reality

    # 3. Closing balance
    if is_future:
        current_real_balance = previous_balance
    else:
        current_real_balance = previous_balance + month_actual_income - month_actual_expenses

    # =========================================================================
    # 4. BILL LIST (MIXES FIXED EXPENSES AND ONE-OFF BILLS)
    # =========================================================================
    fixed_items_status = []
    total_pending_bank = 0  # Unified variable

    # A. Fixed expenses
    for expense in FixedExpense.objects.all():
        if expense.is_credit_card:
            # Credit card subscriptions are settled in a lump sum when the invoice is paid,
            # never individually - so as far as the "to-do list" goes, they're already handled
            status = 'paid'
            amount_paid = expense.expected_amount
        else:
            payment = Transaction.objects.filter(fixed_expense=expense, purchase_date__month=ref_date.month, purchase_date__year=ref_date.year).first()
            status = 'paid' if payment else 'pending'
            amount_paid = payment.total_amount if payment else 0
            if status == 'pending':
                total_pending_bank += expense.expected_amount

        is_overdue = is_current and status == 'pending' and today.day > expense.due_day

        fixed_items_status.append({
            'id': expense.id, 'name': expense.name, 'status': status,
            'expected_amount': expense.expected_amount, 'paid_amount': amount_paid,
            'day': expense.due_day, 'is_credit_card': expense.is_credit_card, 'kind': 'fixed',
            'is_overdue': is_overdue,
        })

    # B. One-off bills (only this month's)
    month_bills_screen = OneOffBill.objects.filter(due_date__month=ref_date.month, due_date__year=ref_date.year)
    for bill in month_bills_screen:
        payment = Transaction.objects.filter(one_off_bill=bill).first()
        status = 'paid' if payment else 'pending'

        if status == 'pending':
            total_pending_bank += bill.amount

        is_overdue = is_current and status == 'pending' and today.day > bill.due_date.day

        fixed_items_status.append({
            'id': bill.id, 'name': bill.title, 'status': status,
            'expected_amount': bill.amount, 'paid_amount': bill.amount if status == 'paid' else 0,
            'day': bill.due_date.day, 'is_credit_card': False, 'kind': 'one_off',
            'is_overdue': is_overdue,
        })

    # Pending items float to the top (overdue first), so what needs attention is seen first
    fixed_items_status.sort(key=lambda item: (
        item['status'] == 'paid',
        not item['is_overdue'],
        item['day'],
    ))
    fixed_items_paid_count = sum(1 for item in fixed_items_status if item['status'] == 'paid')
    fixed_items_total_count = len(fixed_items_status)

    # Final totals
    invoice_paid = Transaction.objects.filter(is_invoice_payment=True, invoice_month=ref_date.month, invoice_year=ref_date.year).exists()

    pending_invoice_amount = 0 if invoice_paid else month_invoice_total
    total_remaining_to_pay = total_pending_bank + pending_invoice_amount

    income_still_expected = forecast_total_income - month_actual_income
    if income_still_expected < 0:
        income_still_expected = 0

    projected_balance = current_real_balance + income_still_expected - total_remaining_to_pay
    forecast_total_expenses = month_actual_expenses + total_remaining_to_pay

    # Last 5 movements (income + expenses combined), so you can glance at the dashboard and
    # immediately see what just happened, without having to open the full statement
    recent_income = Income.objects.order_by('-date', '-id')[:5]
    recent_expenses = Transaction.objects.order_by('-purchase_date', '-id')[:5]

    recent_movements = []
    for income in recent_income:
        recent_movements.append({
            'date': income.date,
            'description': income.description,
            'amount': income.amount,
            'kind': 'income',
        })
    for expense in recent_expenses:
        recent_movements.append({
            'date': expense.purchase_date,
            'description': expense.description,
            'amount': expense.total_amount,
            'kind': 'expense',
            'is_credit_card': expense.is_credit_card,
            'is_internal_transfer': expense.is_internal_transfer,
        })
    recent_movements.sort(key=lambda m: m['date'], reverse=True)
    recent_movements = recent_movements[:5]

    context = {
        'ref_date': ref_date,
        'recent_movements': recent_movements,
        'is_past': is_past, 'is_future': is_future, 'is_current': is_current,
        'prev_month_url': f"?mes={previous_month.month}&ano={previous_month.year}",
        'next_month_url': f"?mes={next_month.month}&ano={next_month.year}",
        'previous_balance': previous_balance,
        'current_balance': current_real_balance,
        'projected_balance': projected_balance,
        'forecast_total_income': forecast_total_income,
        'forecast_total_expenses': forecast_total_expenses,
        'month_actual_income': month_actual_income,
        'month_actual_expenses': month_actual_expenses,
        'fixed_items': fixed_items_status,
        'fixed_items_paid_count': fixed_items_paid_count,
        'fixed_items_total_count': fixed_items_total_count,
        'total_remaining_to_pay': total_remaining_to_pay,
        'invoice_total': month_invoice_total,
        'invoice_line_items': invoice_line_items,
        'invoice_paid': invoice_paid,
        'next_invoice_total': next_invoice_total,
        'total_invested': SavingsBox.objects.aggregate(Sum('current_balance'))['current_balance__sum'] or 0,
        'categories': Category.objects.all(),
    }
    return render(request, 'dashboard.html', context)
