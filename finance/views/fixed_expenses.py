from django.shortcuts import render, redirect
from django.db import transaction
from django.utils import timezone
from decimal import Decimal

from ..models import FixedExpense, Transaction
from ..forms import FixedExpenseForm
from ._helpers import get_owned_or_404


def manage_fixed_expenses(request):
    expenses = FixedExpense.objects.for_user(request.user)
    return render(request, 'fixed_expenses_list.html', {'expenses': expenses})


def new_fixed_expense(request):
    form = FixedExpenseForm(request.POST or None, user=request.user)
    if form.is_valid():
        expense = form.save(commit=False)
        expense.owner = request.user
        expense.save()
        return redirect('gerenciar_fixos')
    return render(request, 'generic_form.html', {'form': form, 'title': '🏠 Novo Gasto Recorrente'})


def delete_fixed_expense(request, id):
    item = get_owned_or_404(request, FixedExpense, id=id)
    item.delete()
    return redirect('gerenciar_fixos')


def pay_fixed_expense(request, id_fixo):
    fixed_expense = get_owned_or_404(request, FixedExpense, id=id_fixo)
    month = request.GET.get('mes', timezone.now().month)
    year = request.GET.get('ano', timezone.now().year)

    if request.method == 'POST':
        actual_amount = Decimal(request.POST.get('valor_real').replace(',', '.'))
        payment_date = request.POST.get('data_pagamento')

        use_credit_card = fixed_expense.is_credit_card
        chosen_card = fixed_expense.credit_card if use_credit_card else None

        # Grabs the savings box set directly on the recurring expense's registration!
        linked_box = fixed_expense.target_savings_box

        with transaction.atomic():
            # 1. Creates the transaction pointing to the right savings box
            Transaction.objects.create(
                owner=request.user,
                description=f"Pgto: {fixed_expense.name}",
                total_amount=actual_amount,
                purchase_date=payment_date,
                fixed_expense=fixed_expense,
                category=fixed_expense.category,
                is_credit_card=use_credit_card,
                credit_card=chosen_card,
                installments_count=1,
                target_savings_box=linked_box
            )

            # 2. Updates the balance only if the expense has a linked savings box
            if linked_box:
                linked_box.current_balance += actual_amount
                linked_box.save()

        return redirect(f'/?mes={month}&ano={year}')

    return render(request, 'pay_fixed_expense.html', {
        'fixed_expense': fixed_expense,
        'mes': month,
        'ano': year,
        'suggested_amount': fixed_expense.expected_amount
    })


def edit_fixed_expense(request, id):
    # Fetches the fixed expense by ID
    expense = get_owned_or_404(request, FixedExpense, id=id)

    # Loads our smart form already pre-filled with the data (instance=expense)
    form = FixedExpenseForm(request.POST or None, instance=expense, user=request.user)

    if form.is_valid():
        form.save()
        # After saving, goes back to the fixed expenses list
        return redirect('gerenciar_fixos')

    # If not POST (when clicking the ✏️ button), opens the form screen!
    return render(request, 'generic_form.html', {
        'form': form,
        'title': f'✏️ Editar Recorrente: {expense.name}'
    })


def remove_fixed_expense(request, id):
    expense = get_owned_or_404(request, FixedExpense, id=id)
    expense.delete()
    return redirect('/')
