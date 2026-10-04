from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils import timezone
from datetime import datetime

from ..models import PeriodicPurchase, Transaction
from ..forms import PeriodicPurchaseForm
from ._helpers import get_owned_or_404


def periodic_purchases(request):
    """Lists everything bought on a longer, irregular cycle (perfume, creme de
    cabelo, hidratante facial...), soonest expected purchase first, so it's easy
    to see what's coming up even though it doesn't happen every month."""
    items = list(PeriodicPurchase.objects.for_user(request.user).select_related('category'))

    today = timezone.now().date()
    rows = []
    for item in items:
        days_left = item.days_until_next(today)
        rows.append({
            'obj': item,
            'next_expected_date': item.next_expected_date,
            'days_left': days_left,
            'overdue_days': abs(days_left) if days_left is not None and days_left < 0 else None,
            'overdue': days_left is not None and days_left < 0,
            'soon': days_left is not None and 0 <= days_left <= 14,
        })

    # Items with no purchase logged yet float to the top (nothing to sort by),
    # then soonest-expected first, then furthest-out last
    rows.sort(key=lambda r: (r['days_left'] is not None, r['days_left'] if r['days_left'] is not None else 0))

    total_estimated_monthly = sum(
        float(item.estimated_amount) / item.interval_months for item in items if item.interval_months > 0
    )

    return render(request, 'periodic_purchases.html', {
        'rows': rows,
        'total_estimated_monthly': total_estimated_monthly,
    })


def new_periodic_purchase(request):
    form = PeriodicPurchaseForm(request.POST or None, user=request.user)
    if form.is_valid():
        item = form.save(commit=False)
        item.owner = request.user
        item.save()
        messages.success(request, f'"{item.name}" adicionado!')
        return redirect('compras_periodicas')
    return render(request, 'generic_form.html', {'form': form, 'title': '🔁 Nova Compra Periódica'})


def edit_periodic_purchase(request, id):
    item = get_owned_or_404(request, PeriodicPurchase, id=id)
    form = PeriodicPurchaseForm(request.POST or None, instance=item, user=request.user)
    if form.is_valid():
        form.save()
        return redirect('compras_periodicas')
    return render(request, 'generic_form.html', {'form': form, 'title': f'✏️ Editar: {item.name}'})


def delete_periodic_purchase(request, id):
    item = get_owned_or_404(request, PeriodicPurchase, id=id)
    item.delete()
    return redirect('compras_periodicas')


def log_periodic_purchase(request, id):
    """Registers today's purchase as a real Transaction (so it shows up in the
    statement/reports like anything else) and rolls the item's 'last purchase'
    forward, which is what pushes its next-expected-date out."""
    item = get_owned_or_404(request, PeriodicPurchase, id=id)

    if request.method == 'POST':
        amount_raw = request.POST.get('valor') or str(item.estimated_amount)
        amount = amount_raw.replace(',', '.')
        date_raw = request.POST.get('data')
        purchase_date = datetime.strptime(date_raw, '%Y-%m-%d').date() if date_raw else timezone.now().date()

        txn = Transaction.objects.create(
            owner=request.user,
            description=item.name,
            total_amount=amount,
            purchase_date=purchase_date,
            category=item.category,
            is_credit_card=False,
            periodic_purchase=item,
        )

        item.last_purchase_date = purchase_date
        if item.is_automatic:
            item.recompute_interval_from_history()
        item.save()
        messages.success(request, f'Compra de "{item.name}" registrada!')

    return redirect('compras_periodicas')
