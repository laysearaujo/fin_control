"""Cross-user data isolation tests - the actual point of adding multi-user support.
Every owned model must be fully invisible and unreachable to a second user, even
when that user knows (or guesses) another user's object id directly in a URL.
"""
from django.contrib.auth.models import User
from django.test import TestCase, Client

from ..models import (
    Category, CreditCard, SavingsBox, FixedIncome, FixedExpense, Income,
    Transaction, OneOffBill, SelfLoan,
)


class CrossUserIsolationTests(TestCase):
    def setUp(self):
        self.user_a = User.objects.create_user(username='user_a', password='pw')
        self.user_b = User.objects.create_user(username='user_b', password='pw')
        self.client_a = Client()
        self.client_a.force_login(self.user_a)
        self.client_b = Client()
        self.client_b.force_login(self.user_b)

        self.category = Category.objects.create(owner=self.user_a, name='Mercado', monthly_cap=100)
        self.card = CreditCard.objects.create(owner=self.user_a, name='Cartão A', limit=1000, closing_day=28, due_day=10)
        self.box = SavingsBox.objects.create(owner=self.user_a, name='Caixinha A', current_balance=500)
        self.fixed_income = FixedIncome.objects.create(owner=self.user_a, description='Salário A', amount=3000, payment_day=5)
        self.fixed_expense = FixedExpense.objects.create(owner=self.user_a, name='Aluguel A', expected_amount=1000, due_day=5)
        self.income = Income.objects.create(owner=self.user_a, description='Salário A', amount=3000, date='2031-01-05')
        self.transaction = Transaction.objects.create(
            owner=self.user_a, description='Compra A', total_amount=100, purchase_date='2031-01-10',
            category=self.category, is_credit_card=False,
        )
        self.bill = OneOffBill.objects.create(owner=self.user_a, title='Conta A', amount=50, due_date='2031-01-15')
        self.loan = SelfLoan.objects.create(
            owner=self.user_a, source_savings_box=self.box, borrowed_amount=100,
            monthly_interest_pct=1, installments_count=3, start_date='2031-01-01',
        )

    # --- Every raw-PK URL that fetches another user's object must 404, never leak/mutate ---

    def test_edit_transaction_404s_for_another_user(self):
        response = self.client_b.get(f'/extrato/editar/{self.transaction.id}/')
        self.assertEqual(response.status_code, 404)

    def test_delete_transaction_does_not_delete_another_users_transaction(self):
        response = self.client_b.get(f'/transacao/apagar/{self.transaction.id}/')
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Transaction.objects.filter(id=self.transaction.id).exists())

    def test_edit_savings_box_404s_for_another_user(self):
        response = self.client_b.get(f'/caixinhas/editar/{self.box.id}/')
        self.assertEqual(response.status_code, 404)

    def test_delete_savings_box_does_not_delete_another_users_box(self):
        response = self.client_b.get(f'/caixinhas/apagar/{self.box.id}/')
        self.assertEqual(response.status_code, 404)
        self.assertTrue(SavingsBox.objects.filter(id=self.box.id).exists())

    def test_savings_box_detail_404s_for_another_user(self):
        response = self.client_b.get(f'/caixinhas/detalhes/{self.box.id}/')
        self.assertEqual(response.status_code, 404)

    def test_edit_credit_card_404s_for_another_user(self):
        response = self.client_b.get(f'/cartoes/editar/{self.card.id}/')
        self.assertEqual(response.status_code, 404)

    def test_delete_credit_card_does_not_delete_another_users_card(self):
        response = self.client_b.get(f'/cartoes/apagar/{self.card.id}/')
        self.assertEqual(response.status_code, 404)
        self.assertTrue(CreditCard.objects.filter(id=self.card.id).exists())

    def test_pay_monthly_invoice_404s_for_another_user(self):
        response = self.client_b.get(f'/fatura/pagar/{self.card.id}/')
        self.assertEqual(response.status_code, 404)

    def test_edit_category_404s_for_another_user(self):
        response = self.client_b.get(f'/categorias/editar/{self.category.id}/')
        # Redirects to the card grid instead of a hard 404 on GET (see edit_category),
        # but must never actually touch user_a's category
        self.assertNotEqual(response.status_code, 200)
        self.category.refresh_from_db()
        self.assertEqual(self.category.name, 'Mercado')

    def test_delete_category_does_not_delete_another_users_category(self):
        response = self.client_b.get(f'/categorias/apagar/{self.category.id}/')
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Category.objects.filter(id=self.category.id).exists())

    def test_edit_fixed_expense_404s_for_another_user(self):
        response = self.client_b.get(f'/editar-fixo/{self.fixed_expense.id}/')
        self.assertEqual(response.status_code, 404)

    def test_delete_fixed_expense_does_not_delete_another_users_expense(self):
        response = self.client_b.get(f'/fixos/apagar/{self.fixed_expense.id}/')
        self.assertEqual(response.status_code, 404)
        self.assertTrue(FixedExpense.objects.filter(id=self.fixed_expense.id).exists())

    def test_pay_fixed_expense_404s_for_another_user(self):
        response = self.client_b.get(f'/fixos/pagar/{self.fixed_expense.id}/')
        self.assertEqual(response.status_code, 404)

    def test_remove_fixed_expense_does_not_delete_another_users_expense(self):
        response = self.client_b.get(f'/excluir-fixo/{self.fixed_expense.id}/')
        self.assertEqual(response.status_code, 404)
        self.assertTrue(FixedExpense.objects.filter(id=self.fixed_expense.id).exists())

    def test_edit_fixed_income_404s_for_another_user(self):
        response = self.client_b.get(f'/receitas-fixas/editar/{self.fixed_income.id}/')
        self.assertEqual(response.status_code, 404)

    def test_delete_fixed_income_does_not_delete_another_users_income(self):
        response = self.client_b.get(f'/receitas-fixas/apagar/{self.fixed_income.id}/')
        self.assertEqual(response.status_code, 404)
        self.assertTrue(FixedIncome.objects.filter(id=self.fixed_income.id).exists())

    def test_edit_income_404s_for_another_user(self):
        response = self.client_b.get(f'/receita/editar/{self.income.id}/')
        self.assertEqual(response.status_code, 404)

    def test_delete_income_does_not_delete_another_users_income(self):
        response = self.client_b.get(f'/receita/excluir/{self.income.id}/')
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Income.objects.filter(id=self.income.id).exists())

    def test_category_expense_detail_404s_for_another_user(self):
        response = self.client_b.get(f'/relatorios/categorias/detalhes/{self.category.id}/')
        self.assertEqual(response.status_code, 404)

    def test_pay_one_off_bill_404s_for_another_user(self):
        response = self.client_b.get(f'/pagar-conta-avulsa/{self.bill.id}/?mes=1&ano=2031')
        self.assertEqual(response.status_code, 404)

    def test_delete_one_off_bill_does_not_delete_another_users_bill(self):
        response = self.client_b.get(f'/apagar-conta-avulsa/{self.bill.id}/')
        self.assertEqual(response.status_code, 404)
        self.assertTrue(OneOffBill.objects.filter(id=self.bill.id).exists())

    def test_edit_one_off_bill_404s_for_another_user(self):
        response = self.client_b.get(f'/editar-conta-avulsa/{self.bill.id}/')
        self.assertEqual(response.status_code, 404)

    # --- List views must never include another user's data ---

    def test_dashboard_never_shows_another_users_categories(self):
        response = self.client_b.get('/')
        self.assertNotIn(self.category, list(response.context['categories']))

    def test_statement_never_shows_another_users_transactions(self):
        response = self.client_b.get('/extrato/')
        all_items = [item for group in response.context['grouped_movements'] for item in group['items']]
        self.assertNotIn(self.transaction.id, [item['id'] for item in all_items])

    def test_savings_boxes_list_never_shows_another_users_box(self):
        response = self.client_b.get('/caixinhas/')
        self.assertNotIn(self.box, list(response.context['boxes']))

    def test_category_cards_never_shows_another_users_category(self):
        response = self.client_b.get('/categorias/cadastro/')
        self.assertNotIn(self.category, list(response.context['categories']))

    def test_credit_cards_list_never_shows_another_users_card(self):
        response = self.client_b.get('/cartoes/')
        self.assertNotIn(self.card, list(response.context['cards']))

    def test_a_brand_new_user_starts_completely_empty(self):
        """Sanity check the other direction - user_a's own data must actually be
        visible to user_a (isolation isn't accidentally hiding everything from everyone)."""
        response = self.client_a.get('/')
        self.assertIn(self.category, list(response.context['categories']))
