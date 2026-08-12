"""Tests for the "cadastro" (registration) popups added across the app: creating a
credit card, fixed expense, fixed income, savings box, or self-loan now opens a
modal on the same page instead of navigating to a full-page form.
"""
from django.utils import timezone

from .helpers import AuthenticatedTestCase
from ..models import Category, CreditCard, FixedExpense, FixedIncome, SavingsBox


class CreditCardPopupTests(AuthenticatedTestCase):
    def test_new_card_modal_is_available_on_the_list_page(self):
        response = self.client.get('/cartoes/')
        self.assertContains(response, 'modalNovoCartao')

    def test_submitting_the_popup_creates_the_card(self):
        response = self.client.post('/cartoes/novo/', {
            'name': 'Cartão Teste', 'limit': '5000.00', 'closing_day': '20', 'due_day': '28',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(CreditCard.objects.filter(owner=self.user, name='Cartão Teste').exists())


class FixedExpensePopupTests(AuthenticatedTestCase):
    def setUp(self):
        super().setUp()
        self.category = Category.objects.create(owner=self.user, name='Serviços Essenciais')

    def test_new_and_edit_modals_are_available_on_the_list_page(self):
        expense = FixedExpense.objects.create(
            owner=self.user, name='Energia', expected_amount=250, due_day=10, category=self.category,
        )
        response = self.client.get('/fixos/')
        self.assertContains(response, 'modalNovoFixo')
        self.assertContains(response, f'modalEditarFixoCadastro{expense.id}')
        self.assertContains(response, f'edit_fixo_{expense.id}_name')

    def test_submitting_the_new_popup_creates_the_expense(self):
        response = self.client.post('/fixos/novo/', {
            'name': 'Internet', 'expected_amount': '120.00', 'due_day': '15', 'category': self.category.id,
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(FixedExpense.objects.filter(owner=self.user, name='Internet').exists())


class FixedIncomePopupTests(AuthenticatedTestCase):
    def test_new_modal_is_available_on_the_list_page(self):
        response = self.client.get('/receitas-fixas/')
        self.assertContains(response, 'modalNovaReceitaFixa')

    def test_submitting_the_popup_creates_the_fixed_income(self):
        response = self.client.post('/receitas-fixas/nova/', {
            'description': 'Salário', 'amount': '5000.00', 'payment_day': '5',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(FixedIncome.objects.filter(owner=self.user, description='Salário').exists())


class SavingsBoxPopupTests(AuthenticatedTestCase):
    def test_new_and_edit_modals_are_available_on_the_list_page(self):
        box = SavingsBox.objects.create(owner=self.user, name='Viagem', current_balance=100)
        response = self.client.get('/caixinhas/')
        self.assertContains(response, 'modalNovaCaixinha')
        self.assertContains(response, f'modalEditarCaixinha{box.id}')

    def test_submitting_the_new_popup_creates_the_box(self):
        response = self.client.post('/caixinhas/nova/', {
            'name': 'Reserva', 'current_balance': '1000.00', 'cdi_target_pct': '102',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(SavingsBox.objects.filter(owner=self.user, name='Reserva').exists())

    def test_edit_modal_is_available_on_the_box_detail_page(self):
        box = SavingsBox.objects.create(owner=self.user, name='Viagem', current_balance=100)
        response = self.client.get(f'/caixinhas/detalhes/{box.id}/')
        self.assertContains(response, 'modalEditarCaixinha')
        self.assertContains(response, 'modalNovoEmprestimo')

    def test_edit_popup_redirects_back_to_the_page_it_was_opened_from(self):
        box = SavingsBox.objects.create(owner=self.user, name='Viagem', current_balance=100)
        response = self.client.post(f'/caixinhas/editar/{box.id}/', {
            'name': 'Viagem 2026', 'cdi_target_pct': '102',
        }, HTTP_REFERER=f'/caixinhas/detalhes/{box.id}/')
        self.assertRedirects(response, f'/caixinhas/detalhes/{box.id}/')
        box.refresh_from_db()
        self.assertEqual(box.name, 'Viagem 2026')
