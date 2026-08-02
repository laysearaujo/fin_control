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
    fixed_incomes = list(FixedIncome.objects.for_user(request.user))
    total_fixed_expense = FixedExpense.objects.for_user(request.user).aggregate(Sum('expected_amount'))['expected_amount__sum'] or 0

    # Loop over the next 12 months
    for i in range(12):
        ref_date = today + relativedelta(months=i)

        # Income actually logged this month (may already include salaries already received)
        actual_income_this_month = Income.objects.filter(
            owner=request.user, date__month=ref_date.month, date__year=ref_date.year
        ).aggregate(Sum('amount'))['amount__sum'] or 0

        # Only forecasts a fixed income if it hasn't already been logged as received this
        # month - otherwise it'd be counted twice (once as "fixed", once as "actual")
        forecast_income = 0
        for fixed_income in fixed_incomes:
            already_received = Income.objects.filter(
                owner=request.user, fixed_income=fixed_income, date__month=ref_date.month, date__year=ref_date.year
            ).exists()
            if not already_received:
                forecast_income += fixed_income.amount

        total_income = actual_income_this_month + forecast_income

        # Installments already committed
        actual_installments = Installment.objects.filter(
            transaction__owner=request.user, due_date__month=ref_date.month, due_date__year=ref_date.year
        ).aggregate(Sum('amount'))['amount__sum'] or 0

        committed = total_fixed_expense + actual_installments

        # Simulation cost
        extra_simulation_cost = 0
        if simulation_active:
            for sim_month in simulated_months:
                if sim_month.month == ref_date.month and sim_month.year == ref_date.year:
                    extra_simulation_cost = simulated_installment_amount
                    break

        # "Saldo Final" always reflects the simulated purchase too, whether it leaves the
        # month positive or tips it into the red - the "+ Simulação" column above still
        # shows the isolated installment amount either way
        final_balance = total_income - committed - extra_simulation_cost

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
