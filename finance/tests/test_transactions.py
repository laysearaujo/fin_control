"""Tests for finance/views/transactions.py: editing/deleting a transaction must
reverse whatever it did to a savings box's balance (and re-apply the new effect on
edit), and receiving income while the real balance is negative must auto-create a
"Pagamento Cheque Especial" label without ever double-counting the deficit.
"""
from datetime import date

from django.utils import timezone

from .helpers import AuthenticatedTestCase
from ..models import Category, CreditCard, SavingsBox, Transaction, Income, Installment


class StatementCreditCardTotalsTests(AuthenticatedTestCase):
    """A parceled credit-card purchase's Transaction.total_amount is the FULL price
    (e.g. R$7880 for a 7x purchase), not what actually left the account that month -
    only the Installment amounts (already counted elsewhere via compute_month_data) do
    that. Counting the raw total here overstated the purchase month's spend."""

    def setUp(self):
        super().setUp()
        self.category = Category.objects.create(owner=self.user, name='Viagens')
        self.card = CreditCard.objects.create(owner=self.user, name='Cartão', limit=10000, closing_day=28, due_day=10)
        self.today = timezone.now().date()

    def test_installment_purchase_total_amount_excluded_from_month_total_expense(self):
        Transaction.objects.create(
            owner=self.user, description='Passagem', total_amount=7880.67, purchase_date=self.today,
            category=self.category, is_credit_card=True, credit_card=self.card, installments_count=7,
        )
        Transaction.objects.create(
            owner=self.user, description='Mercado', total_amount=100, purchase_date=self.today,
            category=self.category, is_credit_card=False,
        )

        response = self.client.get('/extrato/')

        group = response.context['grouped_movements'][0]
        self.assertEqual(group['total_expense'], 100)

    def test_installment_purchase_still_appears_in_the_items_list(self):
        txn = Transaction.objects.create(
            owner=self.user, description='Passagem', total_amount=7880.67, purchase_date=self.today,
            category=self.category, is_credit_card=True, credit_card=self.card, installments_count=7,
        )

        response = self.client.get('/extrato/')

        group = response.context['grouped_movements'][0]
        item = next(i for i in group['items'] if i['id'] == txn.id)
        self.assertEqual(float(item['amount']), 7880.67)
        self.assertEqual(round(float(item['installment_amount']), 2), 1125.81)

    def test_non_installment_credit_card_purchase_also_excluded_from_total(self):
        Transaction.objects.create(
            owner=self.user, description='Compra à vista no cartão', total_amount=200, purchase_date=self.today,
            category=self.category, is_credit_card=True, credit_card=self.card, installments_count=1,
        )

        response = self.client.get('/extrato/')

        group = response.context['grouped_movements'][0]
        self.assertEqual(group['total_expense'], 0)


class SavingsBoxEffectOnEditDeleteTests(AuthenticatedTestCase):
    def setUp(self):
        super().setUp()
        self.reverse_category = Category.objects.create(owner=self.user, name='Aporte Reserva', reverse_logic=True)
        self.normal_category = Category.objects.create(owner=self.user, name='Lazer')
        self.box = SavingsBox.objects.create(owner=self.user, name='Caixinha', current_balance=1000)
        self.today = timezone.now().date()

    def _create_aporte(self, amount):
        response = self.client.post('/despesa/nova/', {
            'description': 'Aporte Teste', 'total_amount': str(amount), 'category': self.reverse_category.id,
            'target_savings_box': self.box.id, 'is_credit_card': '', 'installments_count': '1',
            'purchase_date': str(self.today),
        })
        return Transaction.objects.get(description='Aporte Teste')

    def test_creating_an_aporte_increases_box_balance(self):
        self._create_aporte(200)
        self.box.refresh_from_db()
        self.assertEqual(self.box.current_balance, 1200)

    def test_deleting_an_aporte_reverses_box_balance(self):
        txn = self._create_aporte(200)
        self.client.get(f'/transacao/apagar/{txn.id}/')
        self.box.refresh_from_db()
        self.assertEqual(self.box.current_balance, 1000)

    def test_editing_aporte_amount_adjusts_box_balance_by_the_delta(self):
        txn = self._create_aporte(200)
        self.client.post(f'/extrato/editar/{txn.id}/', {
            'description': 'Aporte Teste', 'total_amount': '350', 'category': self.reverse_category.id,
            'target_savings_box': self.box.id, 'installments_count': '1', 'purchase_date': str(self.today),
        })
        self.box.refresh_from_db()
        self.assertEqual(self.box.current_balance, 1350)

    def test_editing_category_away_from_reverse_logic_reverses_the_effect(self):
        txn = self._create_aporte(200)
        self.client.post(f'/extrato/editar/{txn.id}/', {
            'description': 'Aporte Teste', 'total_amount': '200', 'category': self.normal_category.id,
            'target_savings_box': self.box.id, 'installments_count': '1', 'purchase_date': str(self.today),
        })
        self.box.refresh_from_db()
        self.assertEqual(self.box.current_balance, 1000)

    def test_creating_a_resgate_decreases_box_balance(self):
        self.client.post('/caixinhas/resgatar/', {
            'caixinha_id': self.box.id, 'valor': '150', 'categoria': self.normal_category.id,
            'descricao': 'Resgate Teste',
        })
        self.box.refresh_from_db()
        self.assertEqual(self.box.current_balance, 850)

    def test_deleting_a_resgate_restores_box_balance(self):
        self.client.post('/caixinhas/resgatar/', {
            'caixinha_id': self.box.id, 'valor': '150', 'categoria': self.normal_category.id,
            'descricao': 'Resgate Teste',
        })
        txn = Transaction.objects.get(description__icontains='Resgate Teste')
        self.client.get(f'/transacao/apagar/{txn.id}/')
        self.box.refresh_from_db()
        self.assertEqual(self.box.current_balance, 1000)

    def test_unchecking_credit_card_on_edit_deletes_orphaned_installments(self):
        card = CreditCard.objects.create(owner=self.user, name='Cartão', limit=1000, closing_day=28, due_day=10)
        self.client.post('/despesa/nova/', {
            'description': 'Compra Cartão', 'total_amount': '90', 'category': self.normal_category.id,
            'is_credit_card': 'on', 'credit_card': card.id, 'installments_count': '3',
            'purchase_date': str(self.today),
        })
        txn = Transaction.objects.get(description='Compra Cartão')
        self.assertEqual(Installment.objects.filter(transaction=txn).count(), 3)

        self.client.post(f'/extrato/editar/{txn.id}/', {
            'description': 'Compra Cartão', 'total_amount': '90', 'category': self.normal_category.id,
            'installments_count': '1', 'purchase_date': str(self.today),
        })
        self.assertEqual(Installment.objects.filter(transaction=txn).count(), 0)


class OverdraftPaymentTests(AuthenticatedTestCase):
    """A deficit is "real balance so far < 0". Receiving income while one exists
    must label part of that income as paying it off, without ever creating more
    labels than the deficit actually calls for."""

    def setUp(self):
        super().setUp()
        self.category = Category.objects.create(owner=self.user, name='Lazer')

    def _force_deficit(self, amount, on_date):
        Transaction.objects.create(
            owner=self.user, description='Gasto Grande', total_amount=amount, purchase_date=on_date,
            category=self.category, is_credit_card=False,
        )

    def test_income_covering_full_deficit_creates_matching_payment(self):
        self._force_deficit(500, date(2031, 1, 1))
        self.client.post('/receita/nova/', {
            'description': 'Salário', 'amount': '800', 'date': '2031-02-01',
        })

        payments = Transaction.objects.filter(is_overdraft_payment=True)
        self.assertEqual(payments.count(), 1)
        self.assertEqual(payments.first().total_amount, 500)
        self.assertTrue(payments.first().is_internal_transfer)

    def test_income_smaller_than_deficit_creates_partial_payment(self):
        self._force_deficit(500, date(2031, 1, 1))
        self.client.post('/receita/nova/', {
            'description': 'Salário', 'amount': '200', 'date': '2031-02-01',
        })

        payment = Transaction.objects.get(is_overdraft_payment=True)
        self.assertEqual(payment.total_amount, 200)

    def test_second_income_covers_the_remainder_without_double_labeling(self):
        # Deficit of 500. First income (200) only closes part of the gap - the true
        # deficit shrinks to 300 (500 - 200) by the time the second income arrives, of
        # which 200 was already labeled, leaving only 100 for the second income to cover.
        self._force_deficit(500, date(2031, 1, 1))
        self.client.post('/receita/nova/', {
            'description': 'Salário 1', 'amount': '200', 'date': '2031-02-01',
        })
        self.client.post('/receita/nova/', {
            'description': 'Salário 2', 'amount': '1000', 'date': '2031-03-01',
        })

        payments = Transaction.objects.filter(is_overdraft_payment=True).order_by('purchase_date')
        self.assertEqual(list(payments.values_list('total_amount', flat=True)), [200, 100])

    def test_no_deficit_creates_no_overdraft_payment(self):
        Income.objects.create(owner=self.user, description='Salário', amount=1000, date=date(2031, 1, 1))
        self.client.post('/receita/nova/', {
            'description': 'Salário 2', 'amount': '500', 'date': '2031-02-01',
        })
        self.assertEqual(Transaction.objects.filter(is_overdraft_payment=True).count(), 0)

    def test_overdraft_payment_is_excluded_from_the_real_balance_calc(self):
        """The label itself must never count as a new expense, or the deficit would
        effectively be counted twice."""
        self._force_deficit(500, date(2031, 1, 1))
        self.client.post('/receita/nova/', {
            'description': 'Salário', 'amount': '800', 'date': '2031-02-01',
        })

        from django.db.models import Sum
        total_income = Income.objects.aggregate(Sum('amount'))['amount__sum'] or 0
        total_expense = Transaction.objects.filter(
            is_credit_card=False, is_internal_transfer=False
        ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        # 800 income - 500 real expense = 300, regardless of the R$500 cosmetic label
        self.assertEqual(total_income - total_expense, 300)
