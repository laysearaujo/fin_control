from django.db import models
from django.utils import timezone
from dateutil.relativedelta import relativedelta

# --- BASIC TYPES ---
class Category(models.Model):
    name = models.CharField(max_length=50, verbose_name="Nome")
    monthly_cap = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Teto Mensal (R$)")
    reverse_logic = models.BooleanField(default=False, verbose_name="É uma categoria de Aporte/Reserva?")

    def __str__(self): return self.name

class CreditCard(models.Model):
    name = models.CharField(max_length=50, verbose_name="Nome")
    limit = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Limite (R$)")
    closing_day = models.IntegerField(verbose_name="Dia de Fechamento")
    due_day = models.IntegerField(verbose_name="Dia de Vencimento")

    def __str__(self): return self.name

    def get_actual_due_date(self, purchase_date):
        if purchase_date.day >= self.closing_day:
            next_month = purchase_date + relativedelta(months=1)
            return next_month.replace(day=self.due_day)
        return purchase_date.replace(day=self.due_day)

# --- INVESTMENTS (SAVINGS BOXES) ---
class SavingsBox(models.Model):
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

class SelfLoan(models.Model):
    source_savings_box = models.ForeignKey(SavingsBox, on_delete=models.CASCADE, verbose_name="Caixinha de Origem")
    borrowed_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Valor Emprestado (R$)")
    monthly_interest_pct = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="Juros Mensais (%)", help_text="% de juros que você vai se pagar")
    installments_count = models.IntegerField(verbose_name="Quantidade de Parcelas")
    start_date = models.DateField(default=timezone.now, verbose_name="Data de Início")
    active = models.BooleanField(default=True, verbose_name="Ativo")

    def installment_amount(self):
        # Cálculo simples de juros simples para facilitar (ou Price se quiser avançado)
        total_with_interest = self.borrowed_amount * (1 + (self.monthly_interest_pct / 100 * self.installments_count))
        return total_with_interest / self.installments_count

# --- CASH FLOW ---
class FixedIncome(models.Model):
    description = models.CharField(max_length=100, verbose_name="Descrição")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Valor (R$)")
    payment_day = models.IntegerField(verbose_name="Dia de Recebimento")

class FixedExpense(models.Model):
    name = models.CharField(max_length=100, verbose_name="Nome")
    expected_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Valor Previsto (R$)")
    due_day = models.IntegerField(verbose_name="Dia de Vencimento")
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Categoria")
    is_credit_card = models.BooleanField(default=False, verbose_name="É no Cartão de Crédito?")
    credit_card = models.ForeignKey(CreditCard, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Cartão")
    linked_loan = models.ForeignKey(SelfLoan, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Empréstimo Vinculado")
    target_savings_box = models.ForeignKey('SavingsBox', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Caixinha de Destino", help_text="Se for um aporte, escolha a caixinha de destino")

class Income(models.Model):
    description = models.CharField(max_length=100, verbose_name="Descrição")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Valor (R$)")
    date = models.DateField(default=timezone.now, verbose_name="Data")
    fixed_income = models.ForeignKey(FixedIncome, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Receita Fixa Correspondente")

    def __str__(self):
        return f"{self.description} - R$ {self.amount}"

class Transaction(models.Model):
    description = models.CharField(max_length=100, verbose_name="Descrição")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Valor Total (R$)")
    purchase_date = models.DateField(default=timezone.now, verbose_name="Data da Compra")
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, verbose_name="Categoria")

    is_credit_card = models.BooleanField(default=False, verbose_name="É no Cartão de Crédito?")
    credit_card = models.ForeignKey(CreditCard, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Cartão")
    installments_count = models.IntegerField(default=1, verbose_name="Quantidade de Parcelas")

    fixed_expense = models.ForeignKey(FixedExpense, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Gasto Fixo Correspondente")
    is_invoice_payment = models.BooleanField(default=False, verbose_name="É Pagamento de Fatura?")
    invoice_month = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="Mês da Fatura", help_text="Mês da fatura que este pagamento quita (só para pagamentos de fatura)")
    invoice_year = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="Ano da Fatura", help_text="Ano da fatura que este pagamento quita (só para pagamentos de fatura)")

    one_off_bill = models.ForeignKey('OneOffBill', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Conta Avulsa Correspondente")

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
        if Installment.objects.filter(transaction=self).exists(): return
        installment_amount = self.total_amount / self.installments_count
        base_date = self.purchase_date
        for i in range(self.installments_count):
            current_installment_date = base_date + relativedelta(months=i)
            actual_due_date = self.credit_card.get_actual_due_date(current_installment_date)
            Installment.objects.create(transaction=self, installment_number=i + 1, amount=installment_amount, due_date=actual_due_date)

class Installment(models.Model):
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, verbose_name="Transação")
    installment_number = models.IntegerField(verbose_name="Número da Parcela")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Valor (R$)")
    due_date = models.DateField(verbose_name="Data de Vencimento")
    paid = models.BooleanField(default=False, verbose_name="Pago")

class OneOffBill(models.Model):
    title = models.CharField(max_length=100, verbose_name="Título")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Valor (R$)")
    due_date = models.DateField(verbose_name="Data de Vencimento")
    category = models.ForeignKey('Category', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Categoria")
    installment_group = models.UUIDField(null=True, blank=True, db_index=True, verbose_name="Grupo de Parcelamento", help_text="Compartilhado por todas as parcelas de uma mesma conta extra parcelada")

    def __str__(self):
        return f"{self.title} - {self.due_date}"
