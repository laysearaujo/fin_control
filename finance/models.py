from django.db import models
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from decimal import Decimal

# --- TIPOS BÁSICOS ---
class Categoria(models.Model):
    nome = models.CharField(max_length=50)
    teto_mensal = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    def __str__(self): return self.nome

class CartaoCredito(models.Model):
    nome = models.CharField(max_length=50)
    limite = models.DecimalField(max_digits=10, decimal_places=2)
    dia_fechamento = models.IntegerField()
    dia_vencimento = models.IntegerField()
    def __str__(self): return self.nome
    
    def get_data_vencimento_real(self, data_compra):
        if data_compra.day >= self.dia_fechamento:
            proximo_mes = data_compra + relativedelta(months=1)
            return proximo_mes.replace(day=self.dia_vencimento)
        return data_compra.replace(day=self.dia_vencimento)

# --- INVESTIMENTOS (CAIXINHAS) ---
class Caixinha(models.Model):
    nome = models.CharField(max_length=100) # Ex: Reserva de Emergência
    saldo_atual = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    meta_cdi = models.DecimalField(max_digits=5, decimal_places=2, default=102, help_text="% do CDI (Ex: 100, 102)")
    
    def projecao_mes_seguinte(self):
        # Taxa CDI Mensal Aprox (0.85% ao mês)
        taxa = Decimal(0.0085) * (self.meta_cdi / 100)
        return self.saldo_atual * (1 + taxa)
    
    def __str__(self): return self.nome

class EmprestimoProprio(models.Model):
    caixinha_origem = models.ForeignKey(Caixinha, on_delete=models.CASCADE)
    valor_emprestado = models.DecimalField(max_digits=10, decimal_places=2)
    juros_mensais = models.DecimalField(max_digits=5, decimal_places=2, help_text="% de juros que você vai se pagar")
    qtd_parcelas = models.IntegerField()
    data_inicio = models.DateField(default=timezone.now)
    ativo = models.BooleanField(default=True)
    
    def valor_parcela(self):
        # Cálculo simples de juros simples para facilitar (ou Price se quiser avançado)
        total_com_juros = self.valor_emprestado * (1 + (self.juros_mensais/100 * self.qtd_parcelas))
        return total_com_juros / self.qtd_parcelas

# --- FLUXO DE CAIXA ---
class ReceitaFixa(models.Model):
    descricao = models.CharField(max_length=100)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    dia_recebimento = models.IntegerField()

class GastoFixo(models.Model):
    nome = models.CharField(max_length=100)
    valor_previsto = models.DecimalField(max_digits=10, decimal_places=2)
    dia_vencimento = models.IntegerField()
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, blank=True)
    eh_cartao = models.BooleanField(default=False)
    cartao = models.ForeignKey(CartaoCredito, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Se for um pagamento de empréstimo próprio
    emprestimo_vinculado = models.ForeignKey(EmprestimoProprio, on_delete=models.SET_NULL, null=True, blank=True)

class Receita(models.Model):
    descricao = models.CharField(max_length=100)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    data = models.DateField(default=timezone.now)

class Transacao(models.Model):
    descricao = models.CharField(max_length=100)
    valor_total = models.DecimalField(max_digits=10, decimal_places=2)
    data_compra = models.DateField(default=timezone.now)
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True)
    
    eh_cartao = models.BooleanField(default=False)
    cartao = models.ForeignKey(CartaoCredito, on_delete=models.SET_NULL, null=True, blank=True)
    qtd_parcelas = models.IntegerField(default=1)
    
    gasto_fixo = models.ForeignKey(GastoFixo, on_delete=models.SET_NULL, null=True, blank=True)
    eh_pagamento_fatura = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.eh_cartao and self.cartao:
            self.gerar_parcelas()

    def gerar_parcelas(self):
        if Parcela.objects.filter(transacao=self).exists(): return
        valor_parcela = self.valor_total / self.qtd_parcelas
        data_base = self.data_compra
        for i in range(self.qtd_parcelas):
            data_parcela_atual = data_base + relativedelta(months=i)
            data_vencimento_real = self.cartao.get_data_vencimento_real(data_parcela_atual)
            Parcela.objects.create(transacao=self, numero_parcela=i+1, valor=valor_parcela, data_vencimento=data_vencimento_real)

class Parcela(models.Model):
    transacao = models.ForeignKey(Transacao, on_delete=models.CASCADE)
    numero_parcela = models.IntegerField()
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    data_vencimento = models.DateField()
    pago = models.BooleanField(default=False)