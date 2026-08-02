"""Tests for finance/views/reports.py - the shared month-by-month builder behind the
3-month traffic light (Semáforo) and the 12-month grid, plus the trailing 6-month
average used to suggest an emergency-reserve target.

Both bugs covered here were reported by the user in production: the traffic light
showed a false deficit for the current month before it forecasted income, and the
reserve suggestion came out too low because it averaged in a still-in-progress month.
"""
from datetime import date

from dateutil.relativedelta import relativedelta
from django.utils import timezone

from .helpers import AuthenticatedTestCase
from ..models import Category, FixedExpense, FixedIncome, Transaction
from ..views.reports import _build_month_rows


class BuildMonthRowsForecastTests(AuthenticatedTestCase):
    """_build_month_rows is shared by category_report and annual_report, so a fix here
    fixes both screens at once. Tested directly (not through the view) to isolate it
    from the pie-chart/history code that also lives in category_report."""

    def setUp(self):
        super().setUp()
        self.today = timezone.now().date()
        self.current_month = date(self.today.year, self.today.month, 1)

    def test_current_month_income_is_forecasted_when_nothing_posted_yet(self):
        FixedIncome.objects.create(owner=self.user, description='Salário', amount=5000, payment_day=27)

        rows = _build_month_rows(self.user, [self.current_month], 0.0, self.today, total_recurring_fixed_income=5000.0)

        self.assertEqual(rows[0]['income'], 5000.0)

    def test_past_month_does_not_forecast_income(self):
        last_month = self.current_month - relativedelta(months=1)

        rows = _build_month_rows(self.user, [last_month], 0.0, self.today, total_recurring_fixed_income=5000.0)

        self.assertEqual(rows[0]['income'], 0.0)

    def test_unpaid_bank_fixed_expense_is_forecasted_into_current_month_cost(self):
        category = Category.objects.create(owner=self.user, name='Serviços Essenciais')
        FixedExpense.objects.create(
            owner=self.user, name='Energia', expected_amount=250, due_day=10, category=category, is_credit_card=False,
        )

        rows = _build_month_rows(self.user, [self.current_month], 0.0, self.today, total_recurring_fixed_income=0.0)

        self.assertEqual(rows[0]['cost'], 250.0)

    def test_unpaid_deposit_fixed_expense_is_forecasted_as_a_deposit_not_a_cost(self):
        reserva = Category.objects.create(owner=self.user, name='Aporte Reserva', reverse_logic=True)
        FixedExpense.objects.create(
            owner=self.user, name='Aporte Reserva', expected_amount=2000, due_day=5, category=reserva, is_credit_card=False,
        )

        rows = _build_month_rows(self.user, [self.current_month], 0.0, self.today, total_recurring_fixed_income=0.0)

        self.assertEqual(rows[0]['deposits'], 2000.0)
        self.assertEqual(rows[0]['cost'], 0.0)
        # The aporte still really leaves the checking account, so it must hit the ending balance
        self.assertEqual(rows[0]['ending_balance'], -2000.0)

    def test_already_paid_fixed_expense_is_not_forecasted_again(self):
        category = Category.objects.create(owner=self.user, name='Serviços Essenciais')
        expense = FixedExpense.objects.create(
            owner=self.user, name='Energia', expected_amount=250, due_day=10, category=category, is_credit_card=False,
        )
        Transaction.objects.create(
            owner=self.user, description='Energia', total_amount=250, purchase_date=self.current_month,
            fixed_expense=expense, category=category, is_credit_card=False,
        )

        rows = _build_month_rows(self.user, [self.current_month], 0.0, self.today, total_recurring_fixed_income=0.0)

        # Should reflect the one real payment, not 250 (real) + 250 (forecast)
        self.assertEqual(rows[0]['cost'], 250.0)


class HistoricalAverageExcludesInProgressMonthTests(AuthenticatedTestCase):
    """The reserve suggestion (category_report) averages 'custo real' over the trailing
    6 months. Viewing this on day 1 of a new month used to blend in that near-empty
    month, dragging the average - and the suggested reserve - down."""

    def setUp(self):
        super().setUp()
        self.category = Category.objects.create(owner=self.user, name='Mercado')
        self.today = timezone.now().date()
        self.last_month = date(self.today.year, self.today.month, 1) - relativedelta(months=1)

    def test_in_progress_current_month_is_excluded_from_the_average(self):
        # A complete month with a known real cost
        Transaction.objects.create(
            owner=self.user, description='Mercado', total_amount=4000, purchase_date=self.last_month,
            category=self.category, is_credit_card=False,
        )
        # A tiny sliver of spend in the still-in-progress current month
        Transaction.objects.create(
            owner=self.user, description='Mercado', total_amount=10, purchase_date=self.today,
            category=self.category, is_credit_card=False,
        )

        response = self.client.get('/relatorios/categorias/')

        self.assertEqual(response.context['average_living_cost'], 4000.0)

    def test_falls_back_to_current_month_cost_when_no_complete_month_has_spend(self):
        # Only the in-progress current month has any data - the average would otherwise
        # be stuck at 0 forever for a brand-new user
        Transaction.objects.create(
            owner=self.user, description='Mercado', total_amount=123, purchase_date=self.today,
            category=self.category, is_credit_card=False,
        )

        response = self.client.get('/relatorios/categorias/')

        self.assertEqual(response.context['average_living_cost'], 123.0)
