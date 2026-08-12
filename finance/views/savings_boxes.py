import math
from datetime import timedelta

from dateutil.relativedelta import relativedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Sum, Q
from django.utils import timezone
from django.contrib import messages
from decimal import Decimal

from ..models import SavingsBox, SavingsBoxYieldEvent, Category, Transaction, Income, FixedExpense
from ..forms import SavingsBoxForm, SavingsBoxEditForm, WithdrawSavingsBoxForm
from ._helpers import get_owned_or_404


def _compute_windowed_yield(box, today):
    """How much a box has really yielded in the last 30 days, and in the last 12 months
    (or since it was created, if it's younger than that) - based on logged yield events,
    not a speculative CDI projection"""
    thirty_days_ago = today - timedelta(days=30)
    yield_30_days = SavingsBoxYieldEvent.objects.filter(box=box, date__gte=thirty_days_ago).aggregate(Sum('amount'))['amount__sum'] or 0

    created_date = box.created_at.date()
    one_year_ago = today - timedelta(days=365)
    is_younger_than_12_months = created_date > one_year_ago
    window_start = max(created_date, one_year_ago)
    yield_12_months = SavingsBoxYieldEvent.objects.filter(box=box, date__gte=window_start).aggregate(Sum('amount'))['amount__sum'] or 0

    return {
        'yield_30_days': yield_30_days,
        'yield_12_months': yield_12_months,
        'is_younger_than_12_months': is_younger_than_12_months,
    }


def savings_boxes(request):
    box_list = SavingsBox.objects.for_user(request.user)
    total_saved = box_list.aggregate(Sum('current_balance'))['current_balance__sum'] or 0

    # Handles balance adjustment (mark-to-market)
    if request.method == 'POST' and 'atualizar_saldo' in request.POST:
        box_id = request.POST.get('caixinha_id')
        box = get_owned_or_404(request, SavingsBox, id=box_id)

        try:
            new_value = Decimal(request.POST.get('novo_valor', '').replace(',', '.'))
        except (ValueError, TypeError):
            return redirect('caixinhas')

        # The whole delta from a manual sync is yield - deposits/withdrawals already move
        # current_balance through their own dedicated flows, never through this one
        delta = new_value - box.current_balance
        if delta != 0:
            SavingsBoxYieldEvent.objects.create(box=box, date=timezone.now().date(), amount=delta)

        box.current_balance = new_value
        box.save()
        return redirect('caixinhas')

    today = timezone.now().date()
    for box in box_list:
        windowed = _compute_windowed_yield(box, today)
        box.yield_30_days = windowed['yield_30_days']
        box.yield_12_months = windowed['yield_12_months']
        box.is_younger_than_12_months = windowed['is_younger_than_12_months']
        # Unique auto_id per row so N per-box edit popups on the same page never
        # collide on the same field ids
        box.edit_form = SavingsBoxEditForm(instance=box, auto_id=f'edit_caixinha_{box.id}_%s')

    withdraw_form = WithdrawSavingsBoxForm(user=request.user)
    new_form = SavingsBoxForm(auto_id='new_caixinha_%s')

    return render(request, 'savings_boxes.html', {
        'boxes': box_list, 
        'total': total_saved, 
        'new_form': new_form,
        'withdraw_form': withdraw_form,
    })


def new_savings_box(request):
    form = SavingsBoxForm(request.POST or None)
    if form.is_valid():
        box = form.save(commit=False)
        box.owner = request.user
        box.save()
        return redirect('caixinhas')
    # Invalid popup submission falls back to the classic full-page form so the
    # validation errors are still visible somewhere
    return render(request, 'generic_form.html', {'form': form, 'title': '💰 Nova Caixinha'})


def edit_savings_box(request, id):
    """Allows changing a savings box's settings and goals (not its balance - that's
    handled separately by 'Atualizar valor hoje', which logs the change as yield).
    Now a popup on both the Caixinhas list and the box's own detail page, so it
    redirects back to wherever it was opened from instead of always the list."""
    box = get_owned_or_404(request, SavingsBox, id=id)
    # instance=box pre-fills the generic form with the existing data
    form = SavingsBoxEditForm(request.POST or None, instance=box)

    if form.is_valid():
        form.save()
        return redirect(request.META.get('HTTP_REFERER') or 'caixinhas')

    return render(request, 'generic_form.html', {
        'form': form,
        'title': f'✏️ Editar Caixinha: {box.name}'
    })


def delete_savings_box(request, id):
    """Permanently deletes the virtual savings box"""
    box = get_owned_or_404(request, SavingsBox, id=id)
    box.delete()
    return redirect('caixinhas')


def savings_box_detail(request, id):
    box = get_owned_or_404(request, SavingsBox, id=id)

    # 1. Fetches every deposit/withdrawal linked to this box. Balance syncs ("Atualizar
    # valor hoje") are deliberately left out of this list - they're not a cash movement,
    # just a label for how much yield the box already had. They still show up on the
    # "Evolução do Saldo" chart below, plotted at the date they actually happened.
    history = Transaction.objects.filter(
        Q(target_savings_box=box) | Q(source_savings_box=box)
    ).order_by('-purchase_date', '-id')

    today = timezone.now().date()

    # 2. Goal logic
    amount_left_for_goal = 0
    goal_percentage = 0
    if box.target_amount:
        amount_left_for_goal = max(0, box.target_amount - box.current_balance)
        goal_percentage = min(100, int((box.current_balance / box.target_amount) * 100))

    # How many whole months this box has been growing for, used both for the goal
    # forecast and to turn its average growth into a rate
    created_date = box.created_at.date()
    months_tracked = max(1, (today.year - created_date.year) * 12 + (today.month - created_date.month))
    avg_monthly_growth = (box.current_balance - box.initial_balance) / months_tracked

    # Projects when the goal will be hit based on the box's real average growth pace
    # (aportes - resgates + rendimento) - not a speculative interest rate
    goal_forecast_date = None
    goal_forecast_months = None
    if box.target_amount and amount_left_for_goal > 0 and avg_monthly_growth > 0:
        months_needed = amount_left_for_goal / avg_monthly_growth
        goal_forecast_months = math.ceil(float(months_needed))
        goal_forecast_date = today + relativedelta(months=goal_forecast_months)

    # 3. Real totals (no speculative interest math - just what actually happened)
    total_deposited = Transaction.objects.filter(target_savings_box=box).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    total_withdrawn = Transaction.objects.filter(source_savings_box=box).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    net_movements = total_deposited - total_withdrawn

    # All-time yield, from the logged sync events (not a speculative CDI projection)
    realized_yield = SavingsBoxYieldEvent.objects.filter(box=box).aggregate(Sum('amount'))['amount__sum'] or 0
    windowed = _compute_windowed_yield(box, today)

    # Yield as a % of what was actually put in (principal), so it's comparable to a
    # CDI rate or another investment - not just an absolute R$ figure
    principal_base = box.initial_balance + net_movements
    yield_percentage = (realized_yield / principal_base * 100) if principal_base > 0 else None

    # 4. Balance timeline built event by event (not smoothed by month), so the line
    # actually rises on each deposit/withdrawal and steps on each yield sync, plotted
    # at the date it really happened. Anchored on initial_balance and walked FORWARD
    # (rather than backwards from current_balance) specifically so yield events can be
    # dropped in at their own dates instead of all landing on a single "Início" point.
    # Everything is done in Decimal until the very end to avoid float rounding artifacts
    # (e.g. a withdrawal that should net to exactly zero showing up as -2.27e-13).
    timeline_events = [
        {
            'date': item.purchase_date,
            'order': 0,
            'id': item.id,
            'change': item.total_amount if item.target_savings_box_id == box.id else -item.total_amount,
        }
        for item in history
    ] + [
        {'date': event.date, 'order': 1, 'id': event.id, 'change': event.amount}
        for event in box.yield_events.all()
    ]
    
    # Ordena o gráfico: 1º por data, 2º por tipo (eventos de yield depois), 3º por id
    timeline_events.sort(key=lambda e: (e['date'], e['order'], e['id']))

    balance_labels = ['Início']
    balance_history_decimal = [box.initial_balance]
    running_balance = box.initial_balance
    for event in timeline_events:
        running_balance += event['change']
        balance_labels.append(event['date'].strftime('%d/%m/%y'))
        balance_history_decimal.append(running_balance)
    balance_history = [round(float(value), 2) for value in balance_history_decimal]

    withdraw_form = WithdrawSavingsBoxForm(user=request.user, initial={'source_savings_box': box})

    context = {
        'box': box,
        'edit_form': SavingsBoxEditForm(instance=box),
        'withdraw_form': withdraw_form,
        'history': history,
        'amount_left_for_goal': amount_left_for_goal,
        'goal_percentage': goal_percentage,
        'goal_forecast_date': goal_forecast_date,
        'goal_forecast_months': goal_forecast_months,
        'total_deposited': total_deposited,
        'total_withdrawn': total_withdrawn,
        'realized_yield': realized_yield,
        'yield_percentage': yield_percentage,
        'yield_30_days': windowed['yield_30_days'],
        'yield_12_months': windowed['yield_12_months'],
        'is_younger_than_12_months': windowed['is_younger_than_12_months'],
        'balance_labels': balance_labels,
        'balance_history': balance_history,
    }
    return render(request, 'savings_box_detail.html', context)


def withdraw_savings_box(request):
    if request.method == 'POST':
        # Mantemos o request.META aqui para saber de onde o usuário veio antes do POST
        referer = request.META.get('HTTP_REFERER', 'caixinhas')
        
        form = WithdrawSavingsBoxForm(request.POST, user=request.user)
        
        if form.is_valid():
            box = form.cleaned_data['source_savings_box']
            amount = form.cleaned_data['amount']
            destination = form.cleaned_data['destination']

            if amount > box.current_balance:
                messages.error(request, 'O valor do resgate é maior que o saldo atual da caixinha.')
            else:
                # Subtrai o saldo da caixinha
                box.current_balance -= amount
                box.save()

                if destination == 'SALDO':
                    # 1. Cria a Receita para o dinheiro entrar no saldo livre da conta principal
                    Income.objects.create(
                        owner=request.user,
                        description=f"Resgate da Caixinha: {box.name}",
                        amount=amount,
                        date=timezone.now().date()
                    )
                    
                    # 2. Cria a Transação Interna para o Gráfico e Histórico da Caixinha registrarem a saída
                    Transaction.objects.create(
                        owner=request.user,
                        description=f"Resgate para Saldo Livre",
                        total_amount=amount,
                        purchase_date=timezone.now().date(),
                        source_savings_box=box, 
                        is_internal_transfer=True, # Importante: marca como interna para não sujar suas despesas
                        is_credit_card=False,
                        installments_count=1
                    )
                    messages.success(request, f'Resgate de R$ {amount} enviado para o saldo livre!')

                elif destination == 'DIVIDA':
                    Transaction.objects.create(
                        owner=request.user,
                        description=form.cleaned_data['expense_description'],
                        total_amount=amount,
                        purchase_date=timezone.now().date(),
                        category=form.cleaned_data['expense_category'],
                        source_savings_box=box, 
                        is_credit_card=False,
                        installments_count=1
                    )
                    messages.success(request, 'Dívida paga com sucesso via resgate!')

        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{error}")

        return redirect(referer)
