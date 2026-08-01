"""Tests for finance/views/categories.py: the category card-grid CRUD page (with its
"+ Nova Categoria" modal) and the bulk recategorization tool built after an incident
where real categories/boxes were accidentally deleted.
"""
from django.test import TestCase, Client

from ..models import Category, CreditCard, FixedExpense, OneOffBill, Transaction


class CategoryCardsTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_get_lists_existing_categories(self):
        Category.objects.create(name='Lazer', monthly_cap=200)
        response = self.client.get('/categorias/cadastro/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Lazer')

    def test_post_creates_a_new_category(self):
        response = self.client.post('/categorias/cadastro/', {
            'name': 'Viagens', 'monthly_cap': '500', 'reverse_logic': '',
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Category.objects.filter(name='Viagens', monthly_cap=500).exists())

    def test_post_can_create_a_reverse_logic_category(self):
        self.client.post('/categorias/cadastro/', {
            'name': 'Aporte Reserva', 'monthly_cap': '1000', 'reverse_logic': 'on',
        })
        category = Category.objects.get(name='Aporte Reserva')
        self.assertTrue(category.reverse_logic)

    def test_invalid_post_does_not_create_a_category(self):
        # Missing the required 'name' field
        self.client.post('/categorias/cadastro/', {'monthly_cap': '500'})
        self.assertEqual(Category.objects.count(), 0)


class EditCategoryPopupTests(TestCase):
    """Editing a category is now a popup on the card-grid page (like creating one),
    instead of navigating to the old full-page form."""

    def setUp(self):
        self.client = Client()
        self.category = Category.objects.create(name='Lazer', monthly_cap=200, reverse_logic=False)

    def test_post_updates_the_category_and_redirects_back_to_the_card_grid(self):
        response = self.client.post(f'/categorias/editar/{self.category.id}/', {
            'name': 'Lazer e Cultura', 'monthly_cap': '350.00', 'reverse_logic': '',
        })
        self.assertRedirects(response, '/categorias/cadastro/')
        self.category.refresh_from_db()
        self.assertEqual(self.category.name, 'Lazer e Cultura')
        self.assertEqual(self.category.monthly_cap, 350)
        self.assertFalse(self.category.reverse_logic)

    def test_post_can_turn_on_reverse_logic(self):
        self.client.post(f'/categorias/editar/{self.category.id}/', {
            'name': 'Lazer', 'monthly_cap': '200', 'reverse_logic': 'on',
        })
        self.category.refresh_from_db()
        self.assertTrue(self.category.reverse_logic)

    def test_invalid_post_does_not_change_the_category(self):
        # Missing the required 'name' field
        self.client.post(f'/categorias/editar/{self.category.id}/', {'monthly_cap': '999'})
        self.category.refresh_from_db()
        self.assertEqual(self.category.name, 'Lazer')
        self.assertEqual(self.category.monthly_cap, 200)


class RecategorizePendingTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.category = Category.objects.create(name='Mercado')

    def test_pending_items_without_category_are_listed(self):
        txn = Transaction.objects.create(description='Sem categoria', total_amount=10, is_credit_card=False)
        fixed = FixedExpense.objects.create(name='Sem categoria fixa', expected_amount=20, due_day=5)
        bill = OneOffBill.objects.create(title='Sem categoria avulsa', amount=30, due_date='2031-01-01')

        response = self.client.get('/categorias/recategorizar/')
        self.assertIn(txn, response.context['pending_transactions'])
        self.assertIn(fixed, response.context['pending_fixed_expenses'])
        self.assertIn(bill, response.context['pending_one_off_bills'])

    def test_invoice_payments_are_never_listed_as_pending(self):
        """Invoice payments are lump sums that never have a category by design -
        they must not show up as something that "needs" categorizing."""
        card = CreditCard.objects.create(name='Cartão', limit=1000, closing_day=28, due_day=10)
        Transaction.objects.create(
            description='Pgto Fatura', total_amount=100, is_credit_card=False,
            is_invoice_payment=True, invoice_month=1, invoice_year=2031, credit_card=card,
        )
        response = self.client.get('/categorias/recategorizar/')
        self.assertEqual(list(response.context['pending_transactions']), [])
        self.assertEqual(response.context['total_pending'], 0)

    def test_overdraft_payment_labels_are_never_listed_as_pending(self):
        Transaction.objects.create(
            description='Pagamento Cheque Especial', total_amount=50, is_credit_card=False,
            is_internal_transfer=True, is_overdraft_payment=True,
        )
        response = self.client.get('/categorias/recategorizar/')
        self.assertEqual(list(response.context['pending_transactions']), [])

    def test_post_bulk_assigns_categories(self):
        txn = Transaction.objects.create(description='Sem categoria', total_amount=10, is_credit_card=False)
        fixed = FixedExpense.objects.create(name='Sem categoria fixa', expected_amount=20, due_day=5)

        self.client.post('/categorias/recategorizar/', {
            f'transaction_{txn.id}': str(self.category.id),
            f'fixedexpense_{fixed.id}': str(self.category.id),
        })

        txn.refresh_from_db()
        fixed.refresh_from_db()
        self.assertEqual(txn.category, self.category)
        self.assertEqual(fixed.category, self.category)

    def test_post_with_blank_selection_leaves_category_unset(self):
        txn = Transaction.objects.create(description='Sem categoria', total_amount=10, is_credit_card=False)
        self.client.post('/categorias/recategorizar/', {f'transaction_{txn.id}': ''})
        txn.refresh_from_db()
        self.assertIsNone(txn.category)
