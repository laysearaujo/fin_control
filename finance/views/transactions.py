from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from datetime import date, datetime
from dateutil.relativedelta import relativedelta

from ..models import Transaction, Income, FixedIncome, Installment
from ..forms import TransactionForm, IncomeForm
from .reports import MESES_PT


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
                return redirect('dashboard')
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
        return redirect('dashboard')

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
            saved_txn = form.save()

            # If it's a credit card purchase, rebuild the installments using the card's rules
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
    txn.delete()
    return redirect(request.META.get('HTTP_REFERER', '/'))
