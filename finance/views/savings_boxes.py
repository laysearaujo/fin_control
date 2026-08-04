import math
from datetime import timedelta

from dateutil.relativedelta import relativedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Sum, Q
from django.utils import timezone
from django.contrib import messages
from decimal import Decimal

from ..models import SavingsBox, SavingsBoxYieldEvent, Category, Transaction, Income, FixedExpense, SelfLoan
from ..forms import SavingsBoxForm, SavingsBoxEditForm, SelfLoanForm
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

    new_form = SavingsBoxForm(auto_id='new_caixinha_%s')
    loan_form = SelfLoanForm(user=request.user, auto_id='new_emprestimo_%s')
    return render(request, 'savings_boxes.html', {
        'boxes': box_list, 'total': total_saved, 'new_form': new_form, 'loan_form': loan_form,
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
    ).order_by('-purchase_date')

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
            'change': item.total_amount if item.target_savings_box_id == box.id else -item.total_amount,
        }
        for item in history
    ] + [
        {'date': event.date, 'order': 1, 'change': event.amount}
        for event in box.yield_events.all()
    ]
    timeline_events.sort(key=lambda e: (e['date'], e['order']))

    balance_labels = ['Início']
    balance_history_decimal = [box.initial_balance]
    running_balance = box.initial_balance
    for event in timeline_events:
        running_balance += event['change']
        balance_labels.append(event['date'].strftime('%d/%m/%y'))
        balance_history_decimal.append(running_balance)
    balance_history = [round(float(value), 2) for value in balance_history_decimal]

    context = {
        'box': box,
        'edit_form': SavingsBoxEditForm(instance=box),
        'loan_form': SelfLoanForm(initial={'source_savings_box': box.id}, user=request.user, auto_id='new_emprestimo_%s'),
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
    """Withdraws a partial or total amount from a chosen savings box and logs the transaction in the statement"""
    box_list = SavingsBox.objects.for_user(request.user)
    category_list = Category.objects.for_user(request.user)

    if request.method == 'POST':
        box_id = request.POST.get('caixinha_id')
        withdraw_everything = request.POST.get('zerar_tudo') == 'true'
        category_id = request.POST.get('categoria')
        reason_description = request.POST.get('descricao', '').strip()  # Reason for the withdrawal

        box = get_owned_or_404(request, SavingsBox, id=box_id)
        category_obj = get_owned_or_404(request, Category, id=category_id)

        if withdraw_everything:
            withdrawal_amount = box.current_balance
        else:
            try:
                withdrawal_amount = Decimal(request.POST.get('valor', '0').replace(',', '.'))
            except ValueError:
                withdrawal_amount = Decimal('0.0')

        if withdrawal_amount <= 0 or withdrawal_amount > box.current_balance:
            messages.error(request, f"Valor inválido ou maior que o saldo disponível na caixinha '{box.name}'!")
            return redirect('resgatar_caixinha')

        # 1. Deducts the balance from the chosen savings box
        box.current_balance -= withdrawal_amount
        box.save()

        # 2. Logs the expense in the statement with a clear label
        category_obj = Category.objects.for_user(request.user).filter(id=category_id).first() if category_id else None
        final_description = f"Resgate: {reason_description}" if reason_description else f"Resgate da caixinha {box.name}"

        Transaction.objects.create(
            owner=request.user,
            description=final_description,
            total_amount=withdrawal_amount,
            category=category_obj,
            purchase_date=timezone.now().date(),
            source_savings_box=box,  # Direct link to the box (the box is the SOURCE of the money in a withdrawal)
            is_credit_card=False,
            is_invoice_payment=False,
            is_internal_transfer=True,  # Not a real expense: money just changed location, doesn't hit the overall balance
        )

        messages.success(request, f"Resgate de R$ {withdrawal_amount:.2f} realizado com sucesso da caixinha '{box.name}'!")
        return redirect('caixinhas')

    return render(request, 'withdraw_savings_box_form.html', {
        'boxes': box_list,
        'categories': category_list
    })


def new_self_loan(request):
    # Grabs the box ID from the URL to pre-select it
    box_id = request.GET.get('caixinha_id')
    initial_data = {}
    if box_id:
        initial_data['source_savings_box'] = box_id

    form = SelfLoanForm(request.POST or None, initial=initial_data, user=request.user)

    if form.is_valid():
        loan = form.save(commit=False)
        loan.owner = request.user
        box = loan.source_savings_box

        # 1. Takes the money out of the box
        if box.current_balance < loan.borrowed_amount:
            # Error handling could go here
            pass
        box.current_balance -= loan.borrowed_amount
        box.save()

        # 2. Puts the money into the checking account (Income)
        Income.objects.create(
            owner=request.user,
            description=f"Empréstimo da {box.name}",
            amount=loan.borrowed_amount,
            date=loan.start_date
        )

        # 3. Creates the obligation to pay it back (temporary fixed expense)
        installment_amount = loan.installment_amount()
        loan.save()  # Saves the loan

        FixedExpense.objects.create(
            owner=request.user,
            name=f"Pagamento Empréstimo ({box.name})",
            expected_amount=installment_amount,
            due_day=loan.start_date.day,
            # Category could be "Dívidas"
            linked_loan=loan
        )
        # Note: removing this fixed expense after N installments still needs to be built

        # Popup on both Caixinhas and the box's own detail page - back to wherever
        # it was opened from
        return redirect(request.META.get('HTTP_REFERER') or 'caixinhas')

    # Invalid popup submission falls back to the classic full-page form so the
    # validation errors are still visible somewhere
    return render(request, 'generic_form.html', {'form': form, 'title': '💸 Empréstimo de Mim Mesmo'})
