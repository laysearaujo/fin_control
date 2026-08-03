"""Tests for finance/views/fixed_expenses.py: paying a recurring fixed expense
from the Dashboard's "Contas do Mês" card is now a popup instead of a full-page
navigation, and a fixed expense linked to a savings box (e.g. "Aporte Reserva")
must move the paid amount into that box's balance.
"""
from django.utils import timezone

from .helpers import AuthenticatedTestCase
from ..models import Category, FixedExpense, SavingsBox, Transaction


class PayFixedExpensePopupTests(AuthenticatedTestCase):
    def setUp(self):
        super().setUp()
        self.today = timezone.now().date()
        self.category = Category.objects.create(owner=self.user, name='Serviços Essenciais')
        self.expense = FixedExpense.objects.create(
            owner=self.user, name='Energia', expected_amount=250, due_day=10,
            category=self.category, is_credit_card=False,
        )

    def test_pay_modal_is_available_on_the_dashboard(self):
        response = self.client.get('/')
        self.assertContains(response, f'modalPagarFixo{self.expense.id}')

    def test_submitting_the_popup_pays_the_expense(self):
        response = self.client.post(
            f'/fixos/pagar/{self.expense.id}/?mes={self.today.month}&ano={self.today.year}',
            {'valor_real': '250.00', 'data_pagamento': str(self.today)},
        )

        self.assertEqual(response.status_code, 302)
        txn = Transaction.objects.get(fixed_expense=self.expense)
        self.assertEqual(txn.total_amount, 250)
        self.assertEqual(txn.description, 'Pgto: Energia')

        # Reflected on the dashboard as paid for this month
        dashboard = self.client.get(f'/?mes={self.today.month}&ano={self.today.year}')
        item = next(i for i in dashboard.context['fixed_items'] if i['id'] == self.expense.id)
        self.assertEqual(item['status'], 'paid')

    def test_paying_an_expense_linked_to_a_savings_box_moves_the_money_there(self):
        """The exact bug reported in production: an 'Aporte Reserva' fixed expense
        with a linked savings box must actually credit that box's balance when paid,
        not just create a floating Transaction with no target_savings_box."""
        box = SavingsBox.objects.create(owner=self.user, name='Reserva de Emergência', current_balance=1000)
        aporte_category = Category.objects.create(owner=self.user, name='Aporte Reserva', reverse_logic=True)
        aporte_expense = FixedExpense.objects.create(
            owner=self.user, name='Aporte Reserva', expected_amount=2000, due_day=5,
            category=aporte_category, is_credit_card=False, target_savings_box=box,
        )

        self.client.post(
            f'/fixos/pagar/{aporte_expense.id}/?mes={self.today.month}&ano={self.today.year}',
            {'valor_real': '2000.00', 'data_pagamento': str(self.today)},
        )

        box.refresh_from_db()
        self.assertEqual(box.current_balance, 3000)
        txn = Transaction.objects.get(fixed_expense=aporte_expense)
        self.assertEqual(txn.target_savings_box, box)
