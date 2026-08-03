"""Tests for finance/views/fixed_incomes.py: the "Receber" button on a fixed
income (salary) registers the Income in one click (no intermediate confirmation
page), and editing the fixed income itself is a popup on the same page.
"""
from django.utils import timezone

from .helpers import AuthenticatedTestCase
from ..models import FixedIncome, Income


class ReceiveFixedIncomeTests(AuthenticatedTestCase):
    def setUp(self):
        super().setUp()
        self.today = timezone.now().date()
        # A value with a fractional part matters here: Django templates render
        # DecimalField values locale-formatted (comma decimal separator under
        # LANGUAGE_CODE='pt-br'), which previously broke the hidden/number inputs
        # that carry this value back to the server.
        self.fixed_income = FixedIncome.objects.create(
            owner=self.user, description='Salário', amount=6227.69, payment_day=5,
        )

    def test_clicking_receive_registers_the_income_immediately(self):
        response = self.client.post(f'/receita/nova/?fixa_id={self.fixed_income.id}', {
            'description': self.fixed_income.description,
            'amount': f'{self.fixed_income.amount:.2f}',
            'date': str(self.today),
        })

        self.assertEqual(response.status_code, 302)
        income = Income.objects.get(fixed_income=self.fixed_income)
        self.assertEqual(float(income.amount), float(self.fixed_income.amount))
        self.assertEqual(income.description, 'Salário')

    def test_receive_button_carries_the_amount_with_a_period_not_a_comma(self):
        response = self.client.get('/receitas-fixas/')
        self.assertContains(response, 'value="6227.69"')
        self.assertNotContains(response, 'value="6227,69"')

    def test_edit_popup_is_available_and_updates_the_fixed_income(self):
        response = self.client.get('/receitas-fixas/')
        self.assertContains(response, f'modalEditarReceitaFixa{self.fixed_income.id}')

        self.client.post(f'/receitas-fixas/editar/{self.fixed_income.id}/', {
            'description': 'Salário Novo', 'amount': '7000.00', 'payment_day': '10',
        })

        self.fixed_income.refresh_from_db()
        self.assertEqual(self.fixed_income.description, 'Salário Novo')
        self.assertEqual(self.fixed_income.amount, 7000)
        self.assertEqual(self.fixed_income.payment_day, 10)
