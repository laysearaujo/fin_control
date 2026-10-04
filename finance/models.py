from datetime import date

from django.conf import settings
from django.db import models
from django.utils import timezone
from dateutil.relativedelta import relativedelta


class OwnedQuerySet(models.QuerySet):
    def for_user(self, user):
        return self.filter(owner=user)


class OwnedModel(models.Model):
    """Every top-level model gets its own owner, so each person's data is fully
    isolated from everyone else's - never matched by name/similarity, always by
    this FK. Models that only ever exist hanging off an already-owned parent (e.g.
    Installment off Transaction, SavingsBoxYieldEvent off SavingsBox) don't need
    their own owner - they're implicitly scoped through the CASCADE FK."""
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    objects = OwnedQuerySet.as_manager()

    class Meta:
        abstract = True


# --- BASIC TYPES ---
class Category(OwnedModel):
    name = models.CharField(max_length=50, verbose_name="Nome")
    monthly_cap = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Teto Mensal (R$)")
    reverse_logic = models.BooleanField(default=False, verbose_name="É uma categoria de Aporte/Reserva?")

    def __str__(self): return self.name

class CreditCard(OwnedModel):
    name = models.CharField(max_length=50, verbose_name="Nome")
    limit = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Limite (R$)")
    closing_day = models.IntegerField(
        null=True, 
        blank=True,
        verbose_name="Dia de Fechamento (Deixe em branco se for variável, ex: Santander)"
    )
    due_day = models.IntegerField(verbose_name="Dia de Vencimento")

    def __str__(self): return self.name

    def get_actual_due_date(self, purchase_date):
        """Mantido por compatibilidade - assume fechamento fixo. Cartões de
        fechamento variável (closing_day=None) não têm data de corte previsível
        aqui; quem decide o salto de mês para eles é
        Transaction.generate_installments(), que também considera
        force_next_invoice e o histórico closed_months."""
        if self.closing_day is None:
            return purchase_date.replace(day=self.due_day)
        if purchase_date.day >= self.closing_day:
            next_month = purchase_date + relativedelta(months=1)
            return next_month.replace(day=self.due_day)
        return purchase_date.replace(day=self.due_day)

# --- INVESTMENTS (SAVINGS BOXES) ---
class SavingsBox(OwnedModel):
    name = models.CharField(max_length=100, verbose_name="Nome")  # Ex: Reserva de Emergência
    current_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Saldo Atual (R$)")
    initial_balance = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name="Saldo Inicial (R$)",
        help_text="Congelado na criação da caixinha - não conta como rendimento"
    )
    cdi_target_pct = models.DecimalField(max_digits=5, decimal_places=2, default=102, verbose_name="% do CDI", help_text="% do CDI (Ex: 100, 102)")
    target_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Meta (R$)", help_text="Meta em R$ para esta caixinha (Opcional)")
    description = models.TextField(null=True, blank=True, verbose_name="Descrição", help_text="Para que serve esta caixinha? (Opcional)")
    is_emergency_reserve = models.BooleanField(
        default=False,
        verbose_name="É a sua reserva de emergência?",
        help_text="Marca esta caixinha como sua reserva de emergência para os relatórios (independente do nome dela)"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Criada em")

    def save(self, *args, **kwargs):
        if self._state.adding:
            # Freezes whatever balance the box starts with - it's principal, not yield
            self.initial_balance = self.current_balance
        super().save(*args, **kwargs)

    def __str__(self): return self.name


class SavingsBoxYieldEvent(models.Model):
    """Logs each time a box's balance is manually synced to the real account, so real
    yield can be tracked over time instead of guessed from a CDI-based projection"""
    box = models.ForeignKey(SavingsBox, on_delete=models.CASCADE, related_name='yield_events', verbose_name="Caixinha")
    date = models.DateField(default=timezone.now, verbose_name="Data")
    amount = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Valor do Rendimento (R$)")

    def __str__(self):
        return f"{self.box.name}: R$ {self.amount} em {self.date}"

# --- CASH FLOW ---
class FixedIncome(OwnedModel):
    description = models.CharField(max_length=100, verbose_name="Descrição")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Valor (R$)")
    payment_day = models.IntegerField(verbose_name="Dia de Recebimento")

class FixedExpense(OwnedModel):
    name = models.CharField(max_length=100, verbose_name="Nome")
    expected_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Valor Previsto (R$)")
    due_day = models.IntegerField(verbose_name="Dia de Vencimento")
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Categoria")
    is_credit_card = models.BooleanField(default=False, verbose_name="É no Cartão de Crédito?")
    credit_card = models.ForeignKey(CreditCard, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Cartão")
    target_savings_box = models.ForeignKey('SavingsBox', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Caixinha de Destino", help_text="Se for um aporte, escolha a caixinha de destino")

class Income(OwnedModel):
    description = models.CharField(max_length=100, verbose_name="Descrição")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Valor (R$)")
    date = models.DateField(default=timezone.now, verbose_name="Data")
    fixed_income = models.ForeignKey(FixedIncome, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Receita Fixa Correspondente")

    def __str__(self):
        return f"{self.description} - R$ {self.amount}"

class Transaction(OwnedModel):
    description = models.CharField(max_length=100, verbose_name="Descrição")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Valor Total (R$)")
    purchase_date = models.DateField(default=timezone.now, verbose_name="Data da Compra")
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, verbose_name="Categoria")

    is_credit_card = models.BooleanField(default=False, verbose_name="É no Cartão de Crédito?")
    credit_card = models.ForeignKey(CreditCard, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Cartão")
    installments_count = models.IntegerField(default=1, verbose_name="Quantidade de Parcelas")
    force_next_invoice = models.BooleanField(
        default=False,
        verbose_name="💳 Cartão já fechou? (Adiar para próxima fatura)"
    )

    fixed_expense = models.ForeignKey(FixedExpense, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Gasto Fixo Correspondente")
    is_invoice_payment = models.BooleanField(default=False, verbose_name="É Pagamento de Fatura?")
    invoice_month = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="Mês da Fatura", help_text="Mês da fatura que este pagamento quita (só para pagamentos de fatura)")
    invoice_year = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="Ano da Fatura", help_text="Ano da fatura que este pagamento quita (só para pagamentos de fatura)")

    one_off_bill = models.ForeignKey('OneOffBill', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Conta Avulsa Correspondente")
    periodic_purchase = models.ForeignKey('PeriodicPurchase', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Compra Periódica Correspondente")

    target_savings_box = models.ForeignKey('SavingsBox', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Caixinha de Destino")
    source_savings_box = models.ForeignKey('SavingsBox', on_delete=models.SET_NULL, null=True, blank=True, related_name='outgoing_transactions', verbose_name="Caixinha de Origem")
    is_internal_transfer = models.BooleanField(default=False, verbose_name="É Movimentação Interna?")

    is_overdraft_payment = models.BooleanField(
        default=False, verbose_name="É Pagamento de Cheque Especial?",
        help_text="Rótulo automático criado quando uma receita cobre um saldo negativo de mês anterior - não é gasto novo, por isso também é uma Movimentação Interna"
    )

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_credit_card and self.credit_card:
            self.generate_installments()

    def generate_installments(self):
        """Matemática blindada: decide em quantos meses a compra deve saltar antes
        de gerar as parcelas.

        - Cartões de fechamento fixo (closing_day preenchido, ex: Nubank): pura
          matemática de datas.
        - Cartões de fechamento variável (closing_day em branco, ex: Santander):
          não dá pra calcular sozinho, então confia na memória mensal
          (force_next_invoice desta compra, ou de qualquer outra compra no mesmo
          cartão/mês que já tenha marcado "Já fechou").

        Idempotente: se a transação já tem parcelas, não faz nada (chamado
        automaticamente pelo save(), então precisa ser seguro pra rodar de novo).
        """
        if Installment.objects.filter(transaction=self).exists():
            return

        due_day = self.credit_card.due_day or 1
        closing_day = self.credit_card.closing_day
        installments_count = self.installments_count or 1
        installment_amount = self.total_amount / installments_count
        base_date = self.purchase_date

        months_ahead = 1 if base_date.day > due_day else 0

        card_already_closed = False
        if closing_day is not None:
            if closing_day < due_day:
                card_already_closed = closing_day <= base_date.day <= due_day
            else:
                card_already_closed = base_date.day >= closing_day
        else:
            has_manual_close = Transaction.objects.filter(
                credit_card=self.credit_card,
                force_next_invoice=True,
                purchase_date__year=base_date.year,
                purchase_date__month=base_date.month,
            ).exclude(pk=self.pk).exists()

            if (self.force_next_invoice or has_manual_close) and base_date.day <= due_day:
                card_already_closed = True

        if card_already_closed:
            months_ahead += 1

        base_date += relativedelta(months=months_ahead)

        for i in range(installments_count):
            current_date = base_date + relativedelta(months=i)
            due_day_this_month = min(due_day, 28) if current_date.month == 2 else due_day
            if due_day_this_month == 31 and current_date.month in (4, 6, 9, 11):
                due_day_this_month = 30

            Installment.objects.create(
                transaction=self,
                installment_number=i + 1,
                amount=installment_amount,
                due_date=date(current_date.year, current_date.month, due_day_this_month),
            )

class Installment(models.Model):
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, verbose_name="Transação")
    installment_number = models.IntegerField(verbose_name="Número da Parcela")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Valor (R$)")
    due_date = models.DateField(verbose_name="Data de Vencimento")
    paid = models.BooleanField(default=False, verbose_name="Pago")

class PeriodicPurchase(OwnedModel):
    """Things bought on a longer, irregular cycle (perfume, hair cream, facial
    moisturizer...) - not a monthly FixedExpense, but not a single OneOffBill either.
    Tracks the last purchase and an expected interval so the app can estimate when
    the next one is coming, instead of it just showing up as a surprise expense.

    interval_months can be set by hand (is_automatic=False) or learned from your own
    buying history (is_automatic=True): each time a purchase is confirmed, the interval
    is recalculated as the average gap between all logged purchases, so it drifts
    toward your real pattern instead of staying stuck at a one-time guess."""
    name = models.CharField(max_length=100, verbose_name="Nome")
    estimated_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Valor Estimado (R$)")
    interval_months = models.IntegerField(
        verbose_name="Frequência (a cada quantos meses)", default=3,
        help_text="Se 'Ajustar automaticamente' estiver ativo, isso é só o chute inicial - "
                   "depois de 2+ compras confirmadas o sistema recalcula sozinho."
    )
    is_automatic = models.BooleanField(
        default=False,
        verbose_name="🤖 Ajustar frequência automaticamente pelo histórico?",
        help_text="Recalcula a frequência com base na média real entre as compras confirmadas, "
                   "em vez de manter o número fixo que você digitou."
    )
    last_purchase_date = models.DateField(null=True, blank=True, verbose_name="Última Compra")
    category = models.ForeignKey('Category', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Categoria")
    notes = models.CharField(max_length=200, blank=True, verbose_name="Observações")

    def __str__(self):
        return self.name

    @property
    def next_expected_date(self):
        if not self.last_purchase_date:
            return None
        return self.last_purchase_date + relativedelta(months=self.interval_months)

    def days_until_next(self, today=None):
        next_date = self.next_expected_date
        if next_date is None:
            return None
        today = today or date.today()
        return (next_date - today).days

    def recompute_interval_from_history(self):
        """Averages the gap (in months) between every confirmed purchase, oldest to
        newest. Needs at least 2 logged purchases to say anything - with 0 or 1, the
        manually-set interval_months is left alone as the starting guess. Saves the
        new value on interval_months so it also shows up correctly if the user later
        switches this item back to manual."""
        dates = list(
            Transaction.objects.filter(periodic_purchase=self).order_by('purchase_date').values_list('purchase_date', flat=True)
        )
        if len(dates) < 2:
            return
        gaps_days = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        average_days = sum(gaps_days) / len(gaps_days)
        self.interval_months = max(1, round(average_days / 30.44))


class OneOffBill(OwnedModel):
    title = models.CharField(max_length=100, verbose_name="Título")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Valor (R$)")
    due_date = models.DateField(verbose_name="Data de Vencimento")
    category = models.ForeignKey('Category', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Categoria")
    installment_group = models.UUIDField(null=True, blank=True, db_index=True, verbose_name="Grupo de Parcelamento", help_text="Compartilhado por todas as parcelas de uma mesma conta extra parcelada")

    def __str__(self):
        return f"{self.title} - {self.due_date}"
