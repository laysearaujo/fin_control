from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from datetime import date, datetime
from dateutil.relativedelta import relativedelta

from ..models import Transaction, Income, FixedIncome, Installment, SavingsBox
from ..forms import TransactionForm, IncomeForm
from .reports import MESES_PT


def _reverse_savings_box_effect(txn):
    """Undoes whatever a transaction did to a savings box's balance when it was
    created - an aporte's deposit, or a resgate's withdrawal.

    Boxes are re-fetched by id rather than read off txn.target_savings_box /
    txn.source_savings_box: a form-bound instance caches those related objects
    during validation (ModelChoiceField.clean() resolves and caches them), so
    reading the cached relation here could apply this effect to a stale, pre-edit
    copy of the box and silently overwrite whatever _apply_savings_box_effect
    (or anything else) saved to it in between.
    """
    if txn.target_savings_box_id and txn.category and txn.category.reverse_logic:
        box = SavingsBox.objects.get(id=txn.target_savings_box_id)
        box.current_balance -= txn.total_amount
        box.save()
    if txn.source_savings_box_id:
        box = SavingsBox.objects.get(id=txn.source_savings_box_id)
        box.current_balance += txn.total_amount
        box.save()


def _apply_savings_box_effect(txn):
    """The inverse of _reverse_savings_box_effect - (re)applies a transaction's effect
    on a savings box's balance. See that function's docstring for why boxes are
    re-fetched by id instead of via the cached FK relation."""
    if txn.target_savings_box_id and txn.category and txn.category.reverse_logic:
        box = SavingsBox.objects.get(id=txn.target_savings_box_id)
        box.current_balance += txn.total_amount
        box.save()
    if txn.source_savings_box_id:
        box = SavingsBox.objects.get(id=txn.source_savings_box_id)
        box.current_balance -= txn.total_amount
        box.save()


def _create_overdraft_payment_if_needed(income):
    """When new income arrives and the real balance right before it was negative
    (you were in the "cheque especial"), labels part of that income as paying it off.

    The label is a Transaction with is_overdraft_payment=True AND is_internal_transfer=True:
    the internal-transfer flag is what makes every existing balance calculation
    (dashboard.py, reports.py) already exclude it automatically, so it never double-counts
    the deficit that's already embedded in the running income-minus-expenses math. It only
    exists to make that deficit visible in the Extrato/Dashboard as an explicit line, and
    that's why it's a plain flag rather than something inferred from its description text.

    Because these labels don't affect the real balance, "how much of the deficit is
    already labeled" has to be tracked separately by summing past labels - the real
    balance calculation is blind to them by design.
    """
    real_balance_before = (
        Income.objects.filter(date__lt=income.date).aggregate(Sum('amount'))['amount__sum'] or 0
    ) - (
        Transaction.objects.filter(is_credit_card=False, is_internal_transfer=False, purchase_date__lt=income.date)
        .aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    )

    if real_balance_before >= 0:
        return None

    total_deficit = abs(real_balance_before)

    already_labeled = Transaction.objects.filter(
        is_overdraft_payment=True, purchase_date__lt=income.date
    ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0

    remaining_deficit = total_deficit - already_labeled
    if remaining_deficit <= 0:
        return None

    payment_amount = min(income.amount, remaining_deficit)

    Transaction.objects.create(
        description="Pagamento Cheque Especial",
        total_amount=payment_amount,
        purchase_date=income.date,
        is_credit_card=False,
        is_internal_transfer=True,
        is_overdraft_payment=True,
    )
    return payment_amount


def new_transaction(request):
    if request.method == 'POST':
        form = TransactionForm(request.POST)
        if form.is_valid():
            # Builds the object but doesn't hit the DB yet
            new_transaction_obj = form.save(commit=False)

            try:
                # transaction.atomic() ensures both actions (saving the expense and updating the balance) happen together
                with transaction.atomic():
                    # 1. Saves the transaction to the DB
                    new_transaction_obj.save()

                    # 2. THE DEPOSIT MAGIC:
                    # Checks whether the user picked a savings box AND the category has reverse logic (deposit)
                    if new_transaction_obj.target_savings_box and new_transaction_obj.category.reverse_logic:
                        box = new_transaction_obj.target_savings_box
                        box.current_balance += new_transaction_obj.total_amount
                        box.save()

                messages.success(request, f"Despesa \"{new_transaction_obj.description}\" de R$ {new_transaction_obj.total_amount:.2f} adicionada!")
                return redirect(request.META.get('HTTP_REFERER') or 'dashboard')
            except Exception as e:
                # If something goes wrong, don't crash the app, just log it
                print(f"Erro ao salvar transação: {e}")
    else:
        form = TransactionForm()

    return render(request, 'generic_form.html', {'form': form, 'title': '💸 Nova Despesa'})


def new_income(request):
    """Creates one-off income or settles a fixed income entry"""

    # Checks whether the URL sent the ID of a salary/fixed income
    fixed_income_id = request.GET.get('fixa_id')
    initial_data = {}
    fixed_income = None

    if fixed_income_id:
        try:
            fixed_income = FixedIncome.objects.get(id=fixed_income_id)
            # Auto-fills with the planning data
            initial_data = {
                'description': fixed_income.description,
                'amount': fixed_income.amount,
                'date': timezone.now().date()  # Already defaults to today
            }
        except FixedIncome.DoesNotExist:
            fixed_income = None

    # Loads the form already pre-filled (if there was data)
    form = IncomeForm(request.POST or None, initial=initial_data)

    if form.is_valid():
        income = form.save(commit=False)
        # Links it back to the fixed income it settles, so the dashboard can tell
        # it was received without matching on the description text
        income.fixed_income = fixed_income
        income.save()
        messages.success(request, f"Receita \"{income.description}\" de R$ {income.amount:.2f} adicionada!")

        overdraft_payment = _create_overdraft_payment_if_needed(income)
        if overdraft_payment:
            messages.info(request, f"R$ {overdraft_payment:.2f} dessa receita foi usado pra quitar o cheque especial do saldo negativo anterior.")

        # Skips the referrer when it came pre-filled from a fixed income (e.g. "Receber
        # Salário"), so it lands back on the page that actually made sense: the dashboard
        return redirect('dashboard' if fixed_income else (request.META.get('HTTP_REFERER') or 'dashboard'))

    return render(request, 'generic_form.html', {'form': form, 'title': '💰 Registrar Entrada'})


def statement(request):
    """Lists every movement (income and expenses), filterable by month/year and by text search"""

    month_param = request.GET.get('mes')
    year_param = request.GET.get('ano')
    query = request.GET.get('q', '').strip()

    selected_month = None
    selected_year = None
    try:
        if month_param and year_param:
            selected_month = int(month_param)
            selected_year = int(year_param)
    except ValueError:
        selected_month = None
        selected_year = None

    # 1. Fetches income entries
    income_entries = Income.objects.all()
    if selected_month and selected_year:
        income_entries = income_entries.filter(date__month=selected_month, date__year=selected_year)
    if query:
        income_entries = income_entries.filter(description__icontains=query)
    income_entries = income_entries.order_by('-date')

    # 2. Fetches expense entries
    expense_entries = Transaction.objects.all()
    if selected_month and selected_year:
        expense_entries = expense_entries.filter(purchase_date__month=selected_month, purchase_date__year=selected_year)
    if query:
        expense_entries = expense_entries.filter(description__icontains=query)
    expense_entries = expense_entries.order_by('-purchase_date')

    # 3. Merges both lists manually
    movements = []

    for income in income_entries:
        movements.append({
            'date': income.date,
            'description': income.description,
            'amount': income.amount,
            'kind': 'income',  # Marks it as money coming in
            'id': income.id,
            'source_model': 'income'  # So we know what to delete if needed
        })

    for expense in expense_entries:
        movements.append({
            'date': expense.purchase_date,
            'description': expense.description,
            'amount': expense.total_amount,
            'kind': 'expense',  # Marks it as money going out
            'is_credit_card': expense.is_credit_card,
            'is_overdraft_payment': expense.is_overdraft_payment,
            'id': expense.id,
            'source_model': 'transaction'
        })

    # 4. Sorts the final list by date (most recent first)
    movements.sort(key=lambda x: x['date'], reverse=True)

    # 5. Groups the movements by month, so the statement reads as a timeline instead of
    # one giant flat list. Only the current month starts expanded - the rest start
    # collapsed, since older months are just there for reference
    today = timezone.now().date()
    grouped_movements = []
    current_group = None
    for movement in movements:
        month_key = (movement['date'].year, movement['date'].month)
        if current_group is None or current_group['key'] != month_key:
            current_group = {
                'key': month_key,
                'month_date': date(movement['date'].year, movement['date'].month, 1),
                'items': [],
                'total_income': 0,
                'total_expense': 0,
                # Expanded by default when it's today's real month, or when a mes/ano
                # filter narrowed the statement down to exactly this one
                'is_current_month': month_key == (today.year, today.month) or month_key == (selected_year, selected_month),
            }
            grouped_movements.append(current_group)

        current_group['items'].append(movement)
        if movement['kind'] == 'income':
            current_group['total_income'] += movement['amount']
        else:
            current_group['total_expense'] += movement['amount']

    # 6. Every year that actually has data, so the year dropdown only offers real options
    years_with_data = {d.year for d in Income.objects.dates('date', 'year')}
    years_with_data.update(d.year for d in Transaction.objects.dates('purchase_date', 'year'))
    available_years = sorted(years_with_data, reverse=True) or [timezone.now().year]

    return render(request, 'statement.html', {
        'grouped_movements': grouped_movements,
        'available_years': available_years,
        'months_pt': sorted(MESES_PT.items()),
        'selected_month': selected_month,
        'selected_year': selected_year,
        'query': query,
    })


def edit_transaction(request, id):
    txn = get_object_or_404(Transaction, id=id)

    if request.method == 'POST':
        form = TransactionForm(request.POST, instance=txn)
        if form.is_valid():
            # Snapshots the old state before the form overwrites it in place, so
            # whatever it did to a savings box's balance can be undone first - editing
            # the amount, the category, or which box it's linked to must all be
            # reflected in that box's real balance, not just on the transaction itself
            old_txn = Transaction.objects.get(id=txn.id)
            _reverse_savings_box_effect(old_txn)

            saved_txn = form.save()
            _apply_savings_box_effect(saved_txn)

            # If it's (still) a credit card purchase, rebuild the installments using the card's rules
            if saved_txn.is_credit_card and saved_txn.credit_card:
                # 1. Deletes the old installments linked to this transaction
                Installment.objects.filter(transaction=saved_txn).delete()

                # 2. Calculates the new amount for each installment
                installment_amount = saved_txn.total_amount / saved_txn.installments_count

                # 3. Creates the new installments respecting the card's closing date
                base_date = saved_txn.purchase_date
                for i in range(saved_txn.installments_count):
                    current_installment_date = base_date + relativedelta(months=i)
                    actual_due_date = saved_txn.credit_card.get_actual_due_date(current_installment_date)

                    Installment.objects.create(
                        transaction=saved_txn,
                        installment_number=i + 1,
                        amount=installment_amount,
                        due_date=actual_due_date
                    )
            else:
                # No longer a credit card purchase (or lost its card) - any installments
                # from before the edit would otherwise be orphaned and keep counting
                # toward future invoices
                Installment.objects.filter(transaction=saved_txn).delete()

            return redirect('extrato')
    else:
        form = TransactionForm(instance=txn)

    return render(request, 'generic_form.html', {
        'form': form,
        'title': f'✏️ Editar Transação: {txn.description}'
    })


def delete_transaction(request, id):
    """Allows deleting a wrong entry"""
    txn = get_object_or_404(Transaction, id=id)
    _reverse_savings_box_effect(txn)
    txn.delete()
    return redirect(request.META.get('HTTP_REFERER', '/'))
