from django.shortcuts import render, redirect, get_object_or_404
from datetime import datetime

from ..models import FixedIncome, Income
from ..forms import FixedIncomeForm


def manage_fixed_incomes(request):
    incomes = FixedIncome.objects.all()
    return render(request, 'fixed_incomes_list.html', {'incomes': incomes})


def new_fixed_income(request):
    form = FixedIncomeForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect('gerenciar_receitas_fixas')
    return render(request, 'generic_form.html', {'form': form, 'title': '💰 Novo Salário Fixo'})


def edit_income(request, id):
    # Fetches the income entry by ID
    income = get_object_or_404(Income, id=id)

    if request.method == 'POST':
        # Updates the data coming from the modal
        income.description = request.POST.get('descricao')
        income.amount = request.POST.get('valor')

        # Converts the date text into a date object
        new_date = request.POST.get('data')
        income.date = datetime.strptime(new_date, '%Y-%m-%d').date()

        income.save()

        # Redirects to the income's month (so you can see the change)
        return redirect(f'/?mes={income.date.month}&ano={income.date.year}')

    # If accessed directly without a POST, goes back home
    return redirect('/')


def delete_fixed_income(request, id):
    item = get_object_or_404(FixedIncome, id=id)
    item.delete()
    return redirect('gerenciar_receitas_fixas')


def delete_income(request, id):
    income = Income.objects.get(id=id)
    income.delete()
    return redirect(request.META.get('HTTP_REFERER', '/'))
