from django.shortcuts import render, redirect, get_object_or_404
from django.db import transaction
from django.utils import timezone
from datetime import datetime
from dateutil.relativedelta import relativedelta

from ..models import Transaction, Income, FixedIncome, Installment
from ..forms import TransactionForm, IncomeForm


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
        return redirect('dashboard')

    return render(request, 'generic_form.html', {'form': form, 'title': '💰 Registrar Entrada'})


def statement(request):
    """Lists every movement (income and expenses)"""

    # 1. Fetches income entries
    income_entries = Income.objects.all().order_by('-date')

    # 2. Fetches expense entries
    expense_entries = Transaction.objects.all().order_by('-purchase_date')

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

    return render(request, 'statement.html', {'movements': movements})


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
