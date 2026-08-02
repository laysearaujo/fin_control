"""Tests for finance/views/savings_boxes.py - specifically how balance-sync
("Atualizar valor hoje") events are represented on the box detail page: excluded from
the "Histórico de Movimentações" list (they're not a cash movement, just a yield
label), but plotted on the "Evolução do Saldo" chart at the date they actually
happened, interleaved with real aportes/resgates.
"""
from .helpers import AuthenticatedTestCase
from ..models import Category, SavingsBox, SavingsBoxYieldEvent, Transaction


class SavingsBoxHistoryTests(AuthenticatedTestCase):
    def setUp(self):
        super().setUp()
        self.category = Category.objects.create(owner=self.user, name='Reserva', reverse_logic=True)
        self.box = SavingsBox.objects.create(owner=self.user, name='Caixinha', current_balance=1000)

    def test_yield_event_does_not_appear_in_the_movements_list(self):
        SavingsBoxYieldEvent.objects.create(box=self.box, date='2031-01-15', amount=25)

        response = self.client.get(f'/caixinhas/detalhes/{self.box.id}/')
        self.assertEqual(list(response.context['history']), [])
        self.assertContains(response, 'Nenhuma movimentação registrada ainda.')

    def test_transactions_still_appear_in_the_movements_list(self):
        txn = Transaction.objects.create(
            owner=self.user, description='Aporte', total_amount=100, purchase_date='2031-01-01',
            target_savings_box=self.box, category=self.category, is_credit_card=False,
        )
        response = self.client.get(f'/caixinhas/detalhes/{self.box.id}/')
        self.assertEqual(list(response.context['history']), [txn])

    def test_no_history_shows_empty_state(self):
        response = self.client.get(f'/caixinhas/detalhes/{self.box.id}/')
        self.assertEqual(list(response.context['history']), [])
        self.assertContains(response, 'Nenhuma movimentação registrada ainda.')


class SavingsBoxChartTests(AuthenticatedTestCase):
    """The chart is anchored on initial_balance and walks forward through every
    aporte/resgate/yield event in date order, so the ending point always matches
    current_balance exactly."""

    def setUp(self):
        super().setUp()
        self.category = Category.objects.create(owner=self.user, name='Reserva', reverse_logic=True)

    def test_yield_event_is_plotted_at_its_own_date(self):
        box = SavingsBox.objects.create(owner=self.user, name='Caixinha', current_balance=1000)
        SavingsBoxYieldEvent.objects.create(box=box, date='2031-01-15', amount=-15)

        response = self.client.get(f'/caixinhas/detalhes/{box.id}/')
        self.assertEqual(response.context['balance_labels'], ['Início', '15/01/31'])
        self.assertEqual(response.context['balance_history'], [1000.0, 985.0])

    def test_transactions_and_yield_events_interleave_chronologically(self):
        box = SavingsBox.objects.create(owner=self.user, name='Caixinha', current_balance=0)
        Transaction.objects.create(
            owner=self.user, description='Aporte', total_amount=100, purchase_date='2031-01-01',
            target_savings_box=box, category=self.category, is_credit_card=False,
        )
        SavingsBoxYieldEvent.objects.create(box=box, date='2031-01-15', amount=10)
        Transaction.objects.create(
            owner=self.user, description='Resgate', total_amount=30, purchase_date='2031-01-30',
            source_savings_box=box, is_internal_transfer=True, is_credit_card=False,
        )

        response = self.client.get(f'/caixinhas/detalhes/{box.id}/')
        # initial_balance (0) -> +100 aporte -> +10 yield -> -30 resgate = 80
        self.assertEqual(response.context['balance_history'], [0.0, 100.0, 110.0, 80.0])

    def test_chart_ends_exactly_on_current_balance(self):
        box = SavingsBox.objects.create(owner=self.user, name='Caixinha', current_balance=500, initial_balance=200)
        SavingsBox.objects.filter(id=box.id).update(initial_balance=200)
        Transaction.objects.create(
            owner=self.user, description='Aporte', total_amount=250, purchase_date='2031-01-01',
            target_savings_box=box, category=self.category, is_credit_card=False,
        )
        SavingsBoxYieldEvent.objects.create(box=box, date='2031-02-01', amount=50)

        response = self.client.get(f'/caixinhas/detalhes/{box.id}/')
        self.assertEqual(response.context['balance_history'][-1], 500.0)
