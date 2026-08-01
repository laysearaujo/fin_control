from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Sum
from django.utils import timezone
from datetime import date
from dateutil.relativedelta import relativedelta
from decimal import Decimal

from ..models import Category, FixedIncome, Transaction, Installment, FixedExpense, SavingsBox, OneOffBill
from ..forms import CategoryForm


def _count_pending_categorization():
    """How many Transaction/FixedExpense/OneOffBill rows still need a category
    assigned. Invoice payments and cheque-especial labels are excluded - they're
    lump sums / cosmetic entries that never have a category by design."""
    return (
        Transaction.objects.filter(category__isnull=True, is_invoice_payment=False, is_overdraft_payment=False).count()
        + FixedExpense.objects.filter(category__isnull=True).count()
        + OneOffBill.objects.filter(category__isnull=True).count()
    )


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
    total_fixed_income = FixedIncome.objects.aggregate(Sum('amount'))['amount__sum'] or 0
    categories = Category.objects.all()
    total_planned = categories.aggregate(Sum('monthly_cap'))['monthly_cap__sum'] or 0
    forecast_leftover = total_fixed_income - total_planned

    # --- PER-CATEGORY BREAKDOWN (filtered by the selected month) ---
    categories_with_details = []
    for category in categories:
        # Sums what was already spent in this category for the selected month/year.
        # Includes savings-box withdrawals (is_internal_transfer=True): that money was
        # genuinely spent on something real, it just came from a caixinha instead of the
        # checking account, so it still counts as real spend for budgeting purposes.
        debit_spend = Transaction.objects.filter(
            category=category,
            is_credit_card=False,
            purchase_date__month=ref_date.month,
            purchase_date__year=ref_date.year
        ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0

        card_spend = Installment.objects.filter(
            transaction__category=category,
            due_date__month=ref_date.month,
            due_date__year=ref_date.year
        ).aggregate(Sum('amount'))['amount__sum'] or 0

        card_fixed_expenses = FixedExpense.objects.filter(
            category=category,
            is_credit_card=True
        ).aggregate(Sum('expected_amount'))['expected_amount__sum'] or 0

        # Total spend adds up all 3 (debit + card installments + card subscriptions) for the selected month
        total_spend = debit_spend + card_spend + card_fixed_expenses

        leftover = category.monthly_cap - total_spend

        categories_with_details.append({
            'id': category.id,
            'name': category.name,
            'monthly_cap': category.monthly_cap,
            'total_spent': total_spend,
            'leftover': leftover if leftover > 0 else 0,
            'reverse_logic': category.reverse_logic
        })

    # Fetches the savings boxes for the "save the leftover" modal
    box_list = SavingsBox.objects.all()

    total_pending_categorization = _count_pending_categorization()

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
    category = get_object_or_404(Category, id=id)
    category.delete()
    return redirect('gerenciar_categorias')


def save_leftover(request):
    """Takes money out of the free balance and puts it into a savings box"""
    if request.method == 'POST':
        category_id = request.POST.get('categoria_id')
        box_id = request.POST.get('caixinha_id')
        amount = Decimal(request.POST.get('valor').replace(',', '.'))

        category = get_object_or_404(Category, id=category_id)
        box = get_object_or_404(SavingsBox, id=box_id)

        # 1. Creates an expense to "take" the money out of the month's balance
        Transaction.objects.create(
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
    form = CategoryForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect('gerenciar_categorias')
    return render(request, 'generic_form.html', {'form': form, 'title': '📂 Nova Categoria'})


def category_cards(request):
    """Simple CRUD-style card grid for categories, listed under Cadastros Fixos -
    "+ Nova Categoria" here opens a modal instead of navigating to a new page"""
    if request.method == 'POST':
        form = CategoryForm(request.POST)
        if form.is_valid():
            new_cat = form.save()
            messages.success(request, f"Categoria \"{new_cat.name}\" criada!")
            return redirect('categorias_cadastro')
    else:
        form = CategoryForm()

    return render(request, 'category_cards.html', {
        'categories': Category.objects.all().order_by('name'),
        'form': form,
    })


def edit_category(request, id):
    """Edited via a per-card popup on the Categorias page - if the form is invalid
    (e.g. duplicate name), falls back to the classic full-page form so the errors
    are still visible somewhere."""
    category = get_object_or_404(Category, id=id)
    # instance=category pre-fills the form with the current data
    form = CategoryForm(request.POST or None, instance=category)

    if form.is_valid():
        form.save()
        return redirect('categorias_cadastro')

    if request.method == 'POST':
        return render(request, 'generic_form.html', {
            'form': form,
            'title': f'✏️ Editar Categoria: {category.name}'
        })

    return redirect('categorias_cadastro')


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
            updated += model.objects.filter(id=obj_id).update(category_id=value)

        if updated:
            messages.success(request, f"{updated} item(ns) recategorizado(s)!")
        return redirect('recategorizar_pendentes')

    # Invoice payments and cheque-especial labels are lump sums / cosmetic entries -
    # they never have a category by design (the installments/purchases behind them
    # already carry their own), so they don't belong on a "needs a category" list
    pending_transactions = Transaction.objects.filter(
        category__isnull=True, is_invoice_payment=False, is_overdraft_payment=False
    ).order_by('-purchase_date', '-id')
    pending_fixed_expenses = FixedExpense.objects.filter(category__isnull=True).order_by('name')
    pending_one_off_bills = OneOffBill.objects.filter(category__isnull=True).order_by('-due_date')

    context = {
        'pending_transactions': pending_transactions,
        'pending_fixed_expenses': pending_fixed_expenses,
        'pending_one_off_bills': pending_one_off_bills,
        'total_pending': pending_transactions.count() + pending_fixed_expenses.count() + pending_one_off_bills.count(),
        'categories': Category.objects.all(),
    }
    return render(request, 'recategorize_pending.html', context)
