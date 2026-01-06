from django.db import models
from django.utils import timezone
from dateutil.relativedelta import relativedelta

class Categoria(models.Model):
    nome = models.CharField(max_length=50)
    # Quanto planejo gastar nessa categoria (Orçamento)
    teto_mensal = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Sua meta de gastos para esta categoria")
    
    def __str__(self):
        return f"{self.nome} (Meta: R$ {self.teto_mensal})"

class Receita(models.Model):
    descricao = models.CharField(max_length=100)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    data = models.DateField(default=timezone.now)
    # Se for salário fixo, facilita contas futuras (lógica para depois)
    eh_fixa = models.BooleanField(default=True) 

    def __str__(self):
        return f"{self.descricao} - R$ {self.valor}"

class GastoFixo(models.Model):
    """Contas que chegam todo mês: Aluguel, Internet, Academia"""
    nome = models.CharField(max_length=100)
    valor_previsto = models.DecimalField(max_digits=10, decimal_places=2)
    dia_vencimento = models.IntegerField()
    
    def __str__(self):
        return f"{self.nome} - R$ {self.valor_previsto}"

class CartaoCredito(models.Model):
    nome = models.CharField(max_length=50)
    limite = models.DecimalField(max_digits=10, decimal_places=2)
    dia_fechamento = models.IntegerField()
    dia_vencimento = models.IntegerField()

    def __str__(self):
        return self.nome

    def get_data_vencimento_real(self, data_compra):
        data_fechamento_neste_mes = data_compra.replace(day=self.dia_fechamento)
        if data_compra.day >= self.dia_fechamento:
            proximo_mes = data_compra + relativedelta(months=1)
            return proximo_mes.replace(day=self.dia_vencimento)
        else:
            return data_compra.replace(day=self.dia_vencimento)

class Transacao(models.Model):
    descricao = models.CharField(max_length=100)
    valor_total = models.DecimalField(max_digits=10, decimal_places=2)
    data_compra = models.DateField(default=timezone.now)
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True)
    
    eh_cartao = models.BooleanField(default=False)
    cartao = models.ForeignKey(CartaoCredito, on_delete=models.SET_NULL, null=True, blank=True)
    qtd_parcelas = models.IntegerField(default=1)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.eh_cartao and self.cartao:
            self.gerar_parcelas()

    def gerar_parcelas(self):
        if Parcela.objects.filter(transacao=self).exists():
            return
        valor_parcela = self.valor_total / self.qtd_parcelas
        data_base = self.data_compra
        for i in range(self.qtd_parcelas):
            data_parcela_atual = data_base + relativedelta(months=i)
            data_vencimento_real = self.cartao.get_data_vencimento_real(data_parcela_atual)
            Parcela.objects.create(
                transacao=self, numero_parcela=i+1, valor=valor_parcela,
                data_vencimento=data_vencimento_real
            )

class Parcela(models.Model):
    transacao = models.ForeignKey(Transacao, on_delete=models.CASCADE)
    numero_parcela = models.IntegerField()
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    data_vencimento = models.DateField()
    pago = models.BooleanField(default=False)