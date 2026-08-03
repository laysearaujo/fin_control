from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Sum
from django.utils import timezone
from datetime import date
from dateutil.relativedelta import relativedelta
from decimal import Decimal

from ..models import Category, FixedIncome, Transaction, Installment, FixedExpense, SavingsBox, OneOffBill
from ..forms import CategoryForm
from ._helpers import get_owned_or_404


def _count_pending_categorization(user):
    """How many Transaction/FixedExpense/OneOffBill rows still need a category
    assigned. Invoice payments and cheque-especial labels are excluded - they're
    lump sums / cosmetic entries that never have a category by design."""
    return (
        Transaction.objects.for_user(user).filter(category__isnull=True, is_invoice_payment=False, is_overdraft_payment=False).count()
        + FixedExpense.objects.for_user(user).filter(category__isnull=True).count()
        + OneOffBill.objects.for_user(user).filter(category__isnull=True).count()
    )


def _category_spend_for_month(user, category, month, year):
    """Real spend in a single category for a single month - debit purchases, card
    installments due that month, and card subscriptions (which apply every month
    regardless, same rule as everywhere else this is computed)."""
    debit_spend = Transaction.objects.filter(
        owner=user, category=category, is_credit_card=False,
        purchase_date__month=month, purchase_date__year=year
    ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0

    card_spend = Installment.objects.filter(
        transaction__owner=user, transaction__category=category,
        due_date__month=month, due_date__year=year
    ).aggregate(Sum('amount'))['amount__sum'] or 0

    card_fixed_expenses = FixedExpense.objects.filter(
        owner=user, category=category, is_credit_card=True
    ).aggregate(Sum('expected_amount'))['expected_amount__sum'] or 0

    return debit_spend + card_spend + card_fixed_expenses


def _suggested_cap_for_category(user, category, ref_date, today):
    """Suggests a monthly cap based on the category's own real trailing history -
    averaged over up to 6 months before ref_date, only counting months that
    actually had spend in this category (so a category used every other month
    isn't dragged toward zero by the empty months), and skipping the current
    calendar month since it's still in progress and would understate it."""
    total = 0
    months_with_spend = 0
    for i in range(1, 7):
        month_date = ref_date - relativedelta(months=i)
        if month_date.year == today.year and month_date.month == today.month:
            continue
        spend = _category_spend_for_month(user, category, month_date.month, month_date.year)
        if spend > 0:
            total += spend
            months_with_spend += 1

    return (total / months_with_spend) if months_with_spend else 0


def manage_categories(request):
    month_url = request.GET.get('mes')
    year_url = request.GET.get('ano')
    today = timezone.now().date()

    try:
        if month_url and year_url:
            month_int = int(month_url)
            year_int = int(year_url)

            # Wraps around year boundaries
            if month_int > 12:
                month_int = 1
                year_int += 1
            elif month_int < 1:
                month_int = 12
                year_int -= 1

            ref_date = date(year_int, month_int, 1)
        else:
            ref_date = date(today.year, today.month, 1)

    except (ValueError, TypeError):
        ref_date = date(today.year, today.month, 1)

    # Previous/next month for the arrow links
    previous_month = ref_date - relativedelta(months=1)
    next_month = ref_date + relativedelta(months=1)

    # --- PLANNING SUMMARY ---
    total_fixed_income = FixedIncome.objects.for_user(request.user).aggregate(Sum('amount'))['amount__sum'] or 0
    categories = Category.objects.for_user(request.user)
    total_planned = categories.aggregate(Sum('monthly_cap'))['monthly_cap__sum'] or 0
    forecast_leftover = total_fixed_income - total_planned

    # --- PER-CATEGORY BREAKDOWN (filtered by the selected month) ---
    raw_suggested_caps = {
        category.id: float(_suggested_cap_for_category(request.user, category, ref_date, today))
        for category in categories
    }
    # Suggestions are each computed independently from a category's own history, so
    # nothing stops them from adding up to more than what you actually earn. If they
    # do, every suggestion is scaled down by the same factor so the total suggested
    # budget never exceeds the fixed income - a "smart" suggestion has to fit reality.
    total_raw_suggested = sum(raw_suggested_caps.values())
    scale_factor = 1.0
    if total_fixed_income > 0 and total_raw_suggested > float(total_fixed_income):
        scale_factor = float(total_fixed_income) / total_raw_suggested

    categories_with_details = []
    for category in categories:
        # Sums what was already spent in this category for the selected month/year.
        # Includes savings-box withdrawals (is_internal_transfer=True): that money was
        # genuinely spent on something real, it just came from a caixinha instead of the
        # checking account, so it still counts as real spend for budgeting purposes.
        debit_spend = Transaction.objects.filter(
            owner=request.user,
            category=category,
            is_credit_card=False,
            purchase_date__month=ref_date.month,
            purchase_date__year=ref_date.year
        ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0

        card_spend = Installment.objects.filter(
            transaction__owner=request.user,
            transaction__category=category,
            due_date__month=ref_date.month,
            due_date__year=ref_date.year
        ).aggregate(Sum('amount'))['amount__sum'] or 0

        card_fixed_expenses = FixedExpense.objects.filter(
            owner=request.user,
            category=category,
            is_credit_card=True
        ).aggregate(Sum('expected_amount'))['expected_amount__sum'] or 0

        # Total spend adds up all 3 (debit + card installments + card subscriptions) for the selected month
        total_spend = debit_spend + card_spend + card_fixed_expenses

        leftover = category.monthly_cap - total_spend

        # How close this category is to blowing its cap, so the riskiest ones can
        # float to the top - a reverse_logic (aporte) category has no "risk" in this
        # sense, so it's always treated as safe and sinks to the bottom instead
        usage_pct = 0
        if not category.reverse_logic and category.monthly_cap > 0:
            usage_pct = min(int((total_spend / category.monthly_cap) * 100), 999)

        suggested_cap = raw_suggested_caps[category.id] * scale_factor

        categories_with_details.append({
            'id': category.id,
            'name': category.name,
            'monthly_cap': category.monthly_cap,
            'total_spent': total_spend,
            'leftover': leftover if leftover > 0 else 0,
            'reverse_logic': category.reverse_logic,
            'usage_pct': usage_pct,
            'usage_pct_width': min(usage_pct, 100),
            # A suggestion only really means something if it differs meaningfully
            # from the cap already set - otherwise it's just noise on the screen
            'suggested_cap': suggested_cap if abs(float(suggested_cap) - float(category.monthly_cap)) > 1 else None,
        })

    # Riskiest first (closest to/over the cap), safe and aporte categories last
    categories_with_details.sort(key=lambda c: c['usage_pct'], reverse=True)

    # Fetches the savings boxes for the "save the leftover" modal
    box_list = SavingsBox.objects.for_user(request.user)

    total_pending_categorization = _count_pending_categorization(request.user)

    context = {
        'categories': categories_with_details,
        'total_fixed_income': total_fixed_income,
        'total_planned': total_planned,
        'forecast_leftover': forecast_leftover,
        'boxes': box_list,
        'total_pending_categorization': total_pending_categorization,

        'ref_date': ref_date,
        'prev_month_url': f"?mes={previous_month.month}&ano={previous_month.year}",
        'next_month_url': f"?mes={next_month.month}&ano={next_month.year}",
    }
    return render(request, 'categories_list.html', context)


def delete_category(request, id):
    """Allows deleting a category from the system"""
    category = get_owned_or_404(request, Category, id=id)
    category.delete()
    return redirect('gerenciar_categorias')


def save_leftover(request):
    """Takes money out of the free balance and puts it into a savings box"""
    if request.method == 'POST':
        category_id = request.POST.get('categoria_id')
        box_id = request.POST.get('caixinha_id')
        amount = Decimal(request.POST.get('valor').replace(',', '.'))

        category = get_owned_or_404(request, Category, id=category_id)
        box = get_owned_or_404(request, SavingsBox, id=box_id)

        # 1. Creates an expense to "take" the money out of the month's balance
        Transaction.objects.create(
            owner=request.user,
            description=f"Sobra Guardada: {category.name}",
            total_amount=amount,
            purchase_date=timezone.now().date(),
            category=category,  # Links the category to "zero out" the leftover in the table
            is_credit_card=False
        )

        # 2. Adds the money to the chosen savings box
        box.current_balance += amount
        box.save()

    return redirect('gerenciar_categorias')


def new_category(request):
    form = CategoryForm(request.POST or None, user=request.user)
    if form.is_valid():
        category = form.save(commit=False)
        category.owner = request.user
        category.save()
        return redirect('gerenciar_categorias')
    return render(request, 'generic_form.html', {'form': form, 'title': '📂 Nova Categoria'})


def category_cards(request):
    """Simple CRUD-style card grid for categories, listed under Cadastros Fixos -
    "+ Nova Categoria" here opens a modal instead of navigating to a new page"""
    if request.method == 'POST':
        form = CategoryForm(request.POST, user=request.user)
        if form.is_valid():
            new_cat = form.save(commit=False)
            new_cat.owner = request.user
            new_cat.save()
            messages.success(request, f"Categoria \"{new_cat.name}\" criada!")
            return redirect('categorias_cadastro')
    else:
        form = CategoryForm(user=request.user)

    return render(request, 'category_cards.html', {
        'categories': Category.objects.for_user(request.user).order_by('name'),
        'form': form,
    })


def edit_category(request, id):
    """Edited via a per-card/per-row popup (on both the Categorias page and the
    Planejamento table) - if the form is invalid (e.g. duplicate name), falls back
    to the classic full-page form so the errors are still visible somewhere.
    Redirects back to whichever page the popup was opened from, since this same
    endpoint now serves two different screens."""
    category = get_owned_or_404(request, Category, id=id)
    # instance=category pre-fills the form with the current data
    form = CategoryForm(request.POST or None, instance=category, user=request.user)

    if form.is_valid():
        form.save()
        return redirect(request.META.get('HTTP_REFERER') or 'categorias_cadastro')

    if request.method == 'POST':
        return render(request, 'generic_form.html', {
            'form': form,
            'title': f'✏️ Editar Categoria: {category.name}'
        })

    return redirect(request.META.get('HTTP_REFERER') or 'categorias_cadastro')


def recategorize_pending(request):
    """Bulk-assigns a category to every Transaction/FixedExpense/OneOffBill that
    doesn't have one yet, in a single screen instead of editing each one by one"""
    if request.method == 'POST':
        updated = 0
        for key, value in request.POST.items():
            if not value or '_' not in key:
                continue
            model_name, _, obj_id = key.partition('_')
            model = {'transaction': Transaction, 'fixedexpense': FixedExpense, 'oneoffbill': OneOffBill}.get(model_name)
            if model is None:
                continue
            updated += model.objects.for_user(request.user).filter(id=obj_id).update(category_id=value)

        if updated:
            messages.success(request, f"{updated} item(ns) recategorizado(s)!")
        return redirect('recategorizar_pendentes')

    # Invoice payments and cheque-especial labels are lump sums / cosmetic entries -
    # they never have a category by design (the installments/purchases behind them
    # already carry their own), so they don't belong on a "needs a category" list
    pending_transactions = Transaction.objects.for_user(request.user).filter(
        category__isnull=True, is_invoice_payment=False, is_overdraft_payment=False
    ).order_by('-purchase_date', '-id')
    pending_fixed_expenses = FixedExpense.objects.for_user(request.user).filter(category__isnull=True).order_by('name')
    pending_one_off_bills = OneOffBill.objects.for_user(request.user).filter(category__isnull=True).order_by('-due_date')

    context = {
        'pending_transactions': pending_transactions,
        'pending_fixed_expenses': pending_fixed_expenses,
        'pending_one_off_bills': pending_one_off_bills,
        'total_pending': pending_transactions.count() + pending_fixed_expenses.count() + pending_one_off_bills.count(),
        'categories': Category.objects.for_user(request.user),
    }
    return render(request, 'recategorize_pending.html', context)
