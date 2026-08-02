"""Tests for the checking-balance calculation and multi-card invoice handling in
finance/views/dashboard.py.

These cover the two rules documented in DOCUMENTATION.md that already caused real
bugs during development: resgates must never reduce the checking balance (while
aportes and normal expenses must), and each credit card's invoice/paid-status must
be computed independently of every other card.
"""
from datetime import date

from django.utils import timezone

from .helpers import AuthenticatedTestCase
from ..models import Category, CreditCard, SavingsBox, FixedExpense, Transaction, Income, Installment


class CheckingBalanceTests(AuthenticatedTestCase):
    def setUp(self):
        super().setUp()
        self.category = Category.objects.create(owner=self.user, name='Mercado')
        self.reverse_category = Category.objects.create(owner=self.user, name='Reserva', reverse_logic=True)
        self.box = SavingsBox.objects.create(owner=self.user, name='Caixinha Teste', current_balance=0)
        self.today = timezone.now().date()

    def test_resgate_does_not_reduce_checking_balance(self):
        Income.objects.create(owner=self.user, description='Salário', amount=1000, date=self.today)
        Transaction.objects.create(
            owner=self.user, description='Resgate', total_amount=200, purchase_date=self.today,
            source_savings_box=self.box, is_internal_transfer=True, is_credit_card=False,
        )
        response = self.client.get('/')
        self.assertEqual(response.context['current_balance'], 1000)

    def test_aporte_reduces_checking_balance_like_a_normal_expense(self):
        Income.objects.create(owner=self.user, description='Salário', amount=1000, date=self.today)
        Transaction.objects.create(
            owner=self.user, description='Aporte', total_amount=300, purchase_date=self.today,
            target_savings_box=self.box, category=self.reverse_category, is_credit_card=False,
        )
        response = self.client.get('/')
        self.assertEqual(response.context['current_balance'], 700)

    def test_normal_expense_reduces_checking_balance(self):
        Income.objects.create(owner=self.user, description='Salário', amount=1000, date=self.today)
        Transaction.objects.create(
            owner=self.user, description='Mercado', total_amount=150, purchase_date=self.today,
            category=self.category, is_credit_card=False,
        )
        response = self.client.get('/')
        self.assertEqual(response.context['current_balance'], 850)

    def test_credit_card_purchase_does_not_reduce_checking_balance_directly(self):
        # Credit card spend only hits checking when the invoice is paid, not at purchase time
        card = CreditCard.objects.create(owner=self.user, name='Cartão', limit=1000, closing_day=28, due_day=10)
        Income.objects.create(owner=self.user, description='Salário', amount=1000, date=self.today)
        Transaction.objects.create(
            owner=self.user, description='Compra no cartão', total_amount=300, purchase_date=self.today,
            category=self.category, is_credit_card=True, credit_card=card, installments_count=1,
        )
        response = self.client.get('/')
        self.assertEqual(response.context['current_balance'], 1000)


class MultiCardInvoiceTests(AuthenticatedTestCase):
    """Each card's invoice (total, paid status, next-month accumulation) must be
    computed independently - paying card A must never mark card B as paid."""

    def setUp(self):
        super().setUp()
        self.category = Category.objects.create(owner=self.user, name='Compras')
        self.card_a = CreditCard.objects.create(owner=self.user, name='Cartão A', limit=1000, closing_day=28, due_day=10)
        self.card_b = CreditCard.objects.create(owner=self.user, name='Cartão B', limit=1000, closing_day=28, due_day=10)
        today = timezone.now().date()
        # Day 1 is always before closing_day=28, so the installment lands in this same month
        self.month_start = date(today.year, today.month, 1)

    def _purchase(self, card, amount, description):
        return Transaction.objects.create(
            owner=self.user, description=description, total_amount=amount, purchase_date=self.month_start,
            category=self.category, is_credit_card=True, credit_card=card, installments_count=1,
        )

    def test_cards_invoice_lists_each_card_with_its_own_total(self):
        self._purchase(self.card_a, 100, 'Compra A')
        self._purchase(self.card_b, 250, 'Compra B')

        response = self.client.get('/')
        cards_invoice = {c['card'].id: c for c in response.context['cards_invoice']}

        self.assertEqual(cards_invoice[self.card_a.id]['total'], 100)
        self.assertEqual(cards_invoice[self.card_b.id]['total'], 250)
        self.assertFalse(cards_invoice[self.card_a.id]['paid'])
        self.assertFalse(cards_invoice[self.card_b.id]['paid'])

    def test_paying_one_card_does_not_mark_the_other_as_paid(self):
        self._purchase(self.card_a, 100, 'Compra A')
        self._purchase(self.card_b, 250, 'Compra B')

        due_date = self.card_a.get_actual_due_date(self.month_start)
        self.client.get(f'/fatura/pagar/{self.card_a.id}/?mes={due_date.month}&ano={due_date.year}')

        response = self.client.get('/')
        cards_invoice = {c['card'].id: c for c in response.context['cards_invoice']}

        self.assertTrue(cards_invoice[self.card_a.id]['paid'])
        self.assertFalse(cards_invoice[self.card_b.id]['paid'])

        # Only one is_invoice_payment transaction should exist, tied to card A
        payments = Transaction.objects.filter(is_invoice_payment=True)
        self.assertEqual(payments.count(), 1)
        self.assertEqual(payments.first().credit_card_id, self.card_a.id)


class CreditCardSubscriptionBillListTests(AuthenticatedTestCase):
    """Credit-card FixedExpense subscriptions must never show up as a separate
    pending item in "Contas do Mês" - they're settled via the invoice lump sum, so
    listing them individually would mean they're perpetually (and wrongly) "pending"."""

    def setUp(self):
        super().setUp()
        card = CreditCard.objects.create(owner=self.user, name='Cartão', limit=1000, closing_day=28, due_day=10)
        self.subscription = FixedExpense.objects.create(
            owner=self.user, name='Netflix', expected_amount=39.90, due_day=10,
            is_credit_card=True, credit_card=card,
        )
        self.bank_bill = FixedExpense.objects.create(
            owner=self.user, name='Aluguel', expected_amount=1500, due_day=5, is_credit_card=False,
        )

    def test_credit_card_subscription_excluded_from_fixed_items(self):
        response = self.client.get('/')
        fixed_item_ids = [item['id'] for item in response.context['fixed_items']]
        self.assertNotIn(self.subscription.id, fixed_item_ids)
        self.assertIn(self.bank_bill.id, fixed_item_ids)
