from django.shortcuts import render
from django.db.models import Sum
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from ..models import FixedIncome, FixedExpense, Income, Installment
from ..forms import SimulationForm


def annual_analysis(request):
    today = timezone.now().date()
    months_data = []

    # Simulator logic
    simulation_form = SimulationForm(request.POST or None)
    simulation_active = False
    simulated_installment_amount = 0
    simulated_months = []

    if request.method == 'POST' and simulation_form.is_valid():
        simulation_active = True
        total_amount = simulation_form.cleaned_data['valor_compra']
        installments_count = simulation_form.cleaned_data['parcelas']
        start_date = simulation_form.cleaned_data['inicio_pagamento']

        simulated_installment_amount = total_amount / installments_count
        for i in range(installments_count):
            simulated_months.append(start_date + relativedelta(months=i))

    # Totals (to avoid querying the DB inside the loop)
    total_fixed_income = FixedIncome.objects.aggregate(Sum('amount'))['amount__sum'] or 0
    total_fixed_expense = FixedExpense.objects.aggregate(Sum('expected_amount'))['expected_amount__sum'] or 0

    # Loop over the next 12 months
    for i in range(12):
        ref_date = today + relativedelta(months=i)

        # Extra income for the month (e.g. 13th salary)
        extra_income = Income.objects.filter(
            date__month=ref_date.month,
            date__year=ref_date.year
        ).aggregate(Sum('amount'))['amount__sum'] or 0

        total_income = total_fixed_income + extra_income

        # Installments already committed
        actual_installments = Installment.objects.filter(
            due_date__month=ref_date.month,
            due_date__year=ref_date.year
        ).aggregate(Sum('amount'))['amount__sum'] or 0

        committed = total_fixed_expense + actual_installments

        # Simulation cost
        extra_simulation_cost = 0
        if simulation_active:
            for sim_month in simulated_months:
                if sim_month.month == ref_date.month and sim_month.year == ref_date.year:
                    extra_simulation_cost = simulated_installment_amount
                    break

        final_balance = total_income - (committed + extra_simulation_cost)

        months_data.append({
            'month_name': ref_date.strftime("%b/%Y"),
            'income': float(total_income),
            'committed': float(committed),
            'simulation': float(extra_simulation_cost),
            'balance': float(final_balance),
            'alert': final_balance < 0
        })

    # Chart.js data
    labels = [d['month_name'] for d in months_data]
    data_income = [d['income'] for d in months_data]
    data_actual = [d['committed'] for d in months_data]
    data_simulation = [d['simulation'] for d in months_data]

    return render(request, 'annual_analysis.html', {
        'form': simulation_form,
        'table': months_data,
        'labels': labels,
        'data_income': data_income,
        'data_actual': data_actual,
        'data_simulation': data_simulation,
        'simulation_active': simulation_active
    })
