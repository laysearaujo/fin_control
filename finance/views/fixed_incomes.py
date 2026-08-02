from django.shortcuts import render, redirect

from ..models import FixedIncome, Income
from ..forms import FixedIncomeForm, IncomeForm
from ._helpers import get_owned_or_404


def manage_fixed_incomes(request):
    incomes = FixedIncome.objects.for_user(request.user)
    return render(request, 'fixed_incomes_list.html', {'incomes': incomes})


def new_fixed_income(request):
    form = FixedIncomeForm(request.POST or None)
    if form.is_valid():
        fixed_income = form.save(commit=False)
        fixed_income.owner = request.user
        fixed_income.save()
        return redirect('gerenciar_receitas_fixas')
    return render(request, 'generic_form.html', {'form': form, 'title': '💰 Novo Salário Fixo'})


def edit_fixed_income(request, id):
    # Fetches the fixed income by ID
    income = get_owned_or_404(request, FixedIncome, id=id)

    # Loads the form already pre-filled with the data (instance=income)
    form = FixedIncomeForm(request.POST or None, instance=income)

    if form.is_valid():
        form.save()
        return redirect('gerenciar_receitas_fixas')

    # If not POST (when clicking the ✏️ button), opens the form screen!
    return render(request, 'generic_form.html', {
        'form': form,
        'title': f'✏️ Editar Salário Fixo: {income.description}'
    })


def edit_income(request, id):
    # Fetches the income entry by ID
    income = get_owned_or_404(request, Income, id=id)
    form = IncomeForm(request.POST or None, instance=income)

    if form.is_valid():
        form.save()
        # Redirects to the income's month (so you can see the change)
        return redirect(f'/?mes={income.date.month}&ano={income.date.year}')

    # If not POST (when clicking the ✏️ button), opens the form screen
    return render(request, 'generic_form.html', {
        'form': form,
        'title': f'✏️ Editar Receita: {income.description}'
    })


def delete_fixed_income(request, id):
    item = get_owned_or_404(request, FixedIncome, id=id)
    item.delete()
    return redirect('gerenciar_receitas_fixas')


def delete_income(request, id):
    income = get_owned_or_404(request, Income, id=id)
    income.delete()
    return redirect(request.META.get('HTTP_REFERER', '/'))
