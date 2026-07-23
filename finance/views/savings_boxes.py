from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Sum, Q
from django.utils import timezone
from django.contrib import messages
from dateutil.relativedelta import relativedelta
from decimal import Decimal

from ..models import SavingsBox, Category, Transaction, Income, FixedExpense, SelfLoan
from ..forms import SavingsBoxForm, SelfLoanForm


def savings_boxes(request):
    box_list = SavingsBox.objects.all()
    total_saved = box_list.aggregate(Sum('current_balance'))['current_balance__sum'] or 0

    # Handles balance adjustment (mark-to-market)
    if request.method == 'POST' and 'atualizar_saldo' in request.POST:
        box_id = request.POST.get('caixinha_id')
        new_value = request.POST.get('novo_valor')
        box = SavingsBox.objects.get(id=box_id)
        box.current_balance = new_value
        box.save()
        return redirect('caixinhas')

    return render(request, 'savings_boxes.html', {'boxes': box_list, 'total': total_saved})


def new_savings_box(request):
    form = SavingsBoxForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect('caixinhas')
    return render(request, 'generic_form.html', {'form': form, 'title': '💰 Nova Caixinha'})


def edit_savings_box(request, id):
    """Allows changing a savings box's settings and goals"""
    box = get_object_or_404(SavingsBox, id=id)
    # instance=box pre-fills the generic form with the existing data
    form = SavingsBoxForm(request.POST or None, instance=box)

    if form.is_valid():
        form.save()
        return redirect('caixinhas')

    return render(request, 'generic_form.html', {
        'form': form,
        'title': f'✏️ Editar Caixinha: {box.name}'
    })


def delete_savings_box(request, id):
    """Permanently deletes the virtual savings box"""
    box = get_object_or_404(SavingsBox, id=id)
    box.delete()
    return redirect('caixinhas')


def savings_box_detail(request, id):
    box = get_object_or_404(SavingsBox, id=id)

    # 1. Fetches every deposit/withdrawal linked to this box
    history = Transaction.objects.filter(
        Q(target_savings_box=box) | Q(source_savings_box=box)
    ).order_by('-purchase_date')

    # 2. Goal logic
    amount_left_for_goal = 0
    goal_percentage = 0
    if box.target_amount:
        amount_left_for_goal = max(0, box.target_amount - box.current_balance)
        goal_percentage = min(100, int((box.current_balance / box.target_amount) * 100))

    # 3. Future earnings projection (compound interest based on the CDI rate)
    # Approximate monthly CDI rate (0.85%) adjusted by the box's %
    monthly_rate = Decimal(0.0085) * (box.cdi_target_pct / 100)

    projections = []
    target_months = [1, 3, 6, 12]
    for m in target_months:
        projected_balance = box.current_balance * ((1 + monthly_rate) ** m)
        estimated_profit = projected_balance - box.current_balance
        projections.append({
            'months': m,
            'total': projected_balance,
            'profit': estimated_profit
        })

    # 4. Data for the month-by-month growth chart (historical/future simulation)
    # Generates a line showing the growth trend for the next 6 months
    chart_labels = []
    chart_data = []
    today = timezone.now().date()

    for i in range(7):
        future_date = today + relativedelta(months=i)
        chart_labels.append(future_date.strftime("%b/%y"))
        chart_data.append(float(box.current_balance * ((1 + monthly_rate) ** i)))

    context = {
        'box': box,
        'history': history,
        'amount_left_for_goal': amount_left_for_goal,
        'goal_percentage': goal_percentage,
        'projections': projections,
        'chart_labels': chart_labels,
        'chart_data': chart_data,
    }
    return render(request, 'savings_box_detail.html', context)


def withdraw_savings_box(request):
    """Withdraws a partial or total amount from a chosen savings box and logs the transaction in the statement"""
    box_list = SavingsBox.objects.all()
    category_list = Category.objects.all()

    if request.method == 'POST':
        box_id = request.POST.get('caixinha_id')
        withdraw_everything = request.POST.get('zerar_tudo') == 'true'
        category_id = request.POST.get('categoria')
        reason_description = request.POST.get('descricao', '').strip()  # Reason for the withdrawal

        box = get_object_or_404(SavingsBox, id=box_id)
        category_obj = get_object_or_404(Category, id=category_id)

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
        category_obj = Category.objects.filter(id=category_id).first() if category_id else None
        final_description = f"Resgate: {reason_description}" if reason_description else f"Resgate da caixinha {box.name}"

        Transaction.objects.create(
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

    form = SelfLoanForm(request.POST or None, initial=initial_data)

    if form.is_valid():
        loan = form.save(commit=False)
        box = loan.source_savings_box

        # 1. Takes the money out of the box
        if box.current_balance < loan.borrowed_amount:
            # Error handling could go here
            pass
        box.current_balance -= loan.borrowed_amount
        box.save()

        # 2. Puts the money into the checking account (Income)
        Income.objects.create(
            description=f"Empréstimo da {box.name}",
            amount=loan.borrowed_amount,
            date=loan.start_date
        )

        # 3. Creates the obligation to pay it back (temporary fixed expense)
        installment_amount = loan.installment_amount()
        loan.save()  # Saves the loan

        FixedExpense.objects.create(
            name=f"Pagamento Empréstimo ({box.name})",
            expected_amount=installment_amount,
            due_day=loan.start_date.day,
            # Category could be "Dívidas"
            linked_loan=loan
        )
        # Note: removing this fixed expense after N installments still needs to be built

        return redirect('caixinhas')

    return render(request, 'generic_form.html', {'form': form, 'title': '💸 Empréstimo de Mim Mesmo'})
