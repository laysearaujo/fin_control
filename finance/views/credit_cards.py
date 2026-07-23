from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Sum
from django.utils import timezone

from ..models import CreditCard, Transaction, FixedExpense, Installment
from ..forms import CreditCardForm


def manage_credit_cards(request):
    cards = CreditCard.objects.all()
    return render(request, 'credit_cards_list.html', {'cards': cards})


def new_credit_card(request):
    form = CreditCardForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect('gerenciar_cartoes')
    return render(request, 'generic_form.html', {'form': form, 'title': '💳 Novo Cartão'})


def edit_credit_card(request, id):
    card = get_object_or_404(CreditCard, id=id)

    # Reuses the generic form, pre-filled with the card's data
    form = CreditCardForm(request.POST or None, instance=card)

    if form.is_valid():
        form.save()
        return redirect('gerenciar_cartoes')

    return render(request, 'generic_form.html', {
        'form': form,
        'title': f'✏️ Editar Cartão: {card.name}'
    })


def delete_credit_card(request, id):
    card = get_object_or_404(CreditCard, id=id)
    card.delete()
    return redirect('gerenciar_cartoes')


def pay_monthly_invoice(request):
    # Grabs month/year from the URL, defaults to the current one
    month = int(request.GET.get('mes', timezone.now().month))
    year = int(request.GET.get('ano', timezone.now().year))

    # 1. Calculates the exact amount
    installments_sum = Installment.objects.filter(
        due_date__month=month,
        due_date__year=year
    ).aggregate(Sum('amount'))['amount__sum'] or 0

    subscriptions_sum = 0
    credit_card_fixed_expenses = FixedExpense.objects.filter(is_credit_card=True)
    for expense in credit_card_fixed_expenses:
        already_posted = Transaction.objects.filter(fixed_expense=expense, purchase_date__month=month, purchase_date__year=year).exists()
        if not already_posted:
            subscriptions_sum += expense.expected_amount

    total_invoice = installments_sum + subscriptions_sum

    # 2. Creates the payment (if there's an amount to pay)
    if total_invoice > 0:
        # Checks it doesn't already exist, to avoid duplicating it
        already_paid = Transaction.objects.filter(is_invoice_payment=True, invoice_month=month, invoice_year=year).exists()

        if not already_paid:
            Transaction.objects.create(
                description=f"Pgto Fatura Cartão ({month}/{year})",
                total_amount=total_invoice,
                purchase_date=timezone.now().date(),  # Leaves the balance TODAY
                is_credit_card=False,  # Comes out of the checking account (debit)
                is_invoice_payment=True,  # MARKS THE INVOICE AS PAID
                invoice_month=month,
                invoice_year=year,
            )

    # 3. The trick: redirects back to the month you were looking at!
    # If you paid February's invoice, it takes you back to February.
    return redirect(f'/?mes={month}&ano={year}')
