from django.shortcuts import redirect
from django.utils import timezone
from datetime import datetime
from dateutil.relativedelta import relativedelta

from ..models import Category, OneOffBill, Transaction


def add_one_off_bill(request):
    if request.method == 'POST':
        title = request.POST.get('titulo')
        # Swaps the comma for a dot to avoid errors when saving
        amount = request.POST.get('valor').replace(',', '.')
        due_date_str = request.POST.get('data_vencimento')
        category_id = request.POST.get('categoria_id')

        # Grabs how many months to repeat it for (defaults to 1 if nothing is sent)
        months_count = int(request.POST.get('qtd_meses', 1))

        # Fetches the category object from the DB
        category_obj = None
        if category_id:
            category_obj = Category.objects.get(id=category_id)

        due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()

        # THE TRICK HERE: creates one bill per month
        for i in range(months_count):
            # Advances the month on each repetition
            installment_date = due_date + relativedelta(months=i)

            # Adds (1/3), (2/3) to the title if it's split across months
            installment_title = title
            if months_count > 1:
                installment_title = f"{title} ({i+1}/{months_count})"

            OneOffBill.objects.create(
                title=installment_title,
                amount=amount,
                due_date=installment_date,
                category=category_obj
            )

        return redirect(f'/?mes={due_date.month}&ano={due_date.year}')

    return redirect('/')


def pay_one_off_bill(request, id):
    bill = OneOffBill.objects.get(id=id)

    # Creates the transaction using the category already set on the one-off bill
    Transaction.objects.create(
        description=bill.title,
        total_amount=bill.amount,
        purchase_date=timezone.now().date(),
        is_credit_card=False,
        one_off_bill_id=id,
        category=bill.category  # Passes the category along
    )

    month = request.GET.get('mes')
    year = request.GET.get('ano')
    return redirect(f'/?mes={month}&ano={year}')


def delete_one_off_bill(request, id):
    bill = OneOffBill.objects.get(id=id)

    # Saves the date so we can redirect to the right month
    month = bill.due_date.month
    year = bill.due_date.year

    bill.delete()

    return redirect(f'/?mes={month}&ano={year}')


def edit_one_off_bill(request, id):
    bill = OneOffBill.objects.get(id=id)

    if request.method == 'POST':
        bill.title = request.POST.get('titulo')
        bill.amount = request.POST.get('valor')

        # Converts the date string into a date object
        new_due_date = request.POST.get('data_vencimento')
        bill.due_date = datetime.strptime(new_due_date, '%Y-%m-%d').date()

        category_id = request.POST.get('categoria_id')
        if category_id:
            bill.category_id = category_id

        bill.save()

        # IF IT'S ALREADY PAID, UPDATES THE TRANSACTION TOO
        txn = Transaction.objects.filter(one_off_bill=bill).first()
        if txn:
            txn.description = bill.title
            txn.total_amount = bill.amount
            txn.category = bill.category
            # Keeps the original payment date
            txn.save()

        # Redirects to the month of the NEW due date
        return redirect(f'/?mes={bill.due_date.month}&ano={bill.due_date.year}')

    return redirect('/')
