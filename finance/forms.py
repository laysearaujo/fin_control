from django import forms
from .models import Transacao, Receita, CartaoCredito, Categoria, GastoFixo, ReceitaFixa, Caixinha, EmprestimoProprio

# Estilo padrão para todos os inputs ficarem bonitos
class BootstrapModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-control form-control-lg'

class TransacaoForm(BootstrapModelForm):
    class Meta:
        model = Transacao
        fields = ['descricao', 'valor_total', 'categoria', 'eh_cartao', 'cartao', 'qtd_parcelas', 'data_compra']
        widgets = {
            'data_compra': forms.DateInput(attrs={'type': 'date'}),
            'descricao': forms.TextInput(attrs={'placeholder': 'Ex: Mercado, Uber...'}),
            'categoria': forms.Select(attrs={'class': 'form-select'}),
            'eh_cartao': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch', 'id': 'check_cartao'}),
            
            'cartao': forms.Select(attrs={'class': 'form-select'}),
            'qtd_parcelas': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'value': 1}),
        }

class ReceitaFixaForm(BootstrapModelForm):
    class Meta:
        model = ReceitaFixa
        fields = ['descricao', 'valor', 'dia_recebimento']
        widgets = {
             'descricao': forms.TextInput(attrs={'placeholder': 'Ex: Salário Mensal, Aluguel...'}),
             'dia_recebimento': forms.NumberInput(attrs={'max': 31, 'min': 1}),
        }

class ReceitaForm(BootstrapModelForm):
    class Meta:
        model = Receita
        fields = ['descricao', 'valor', 'data']
        widgets = {
            'data': forms.DateInput(attrs={'type': 'date'}),
        }

class CartaoForm(BootstrapModelForm):
    class Meta:
        model = CartaoCredito
        fields = ['nome', 'limite', 'dia_fechamento', 'dia_vencimento']
        widgets = {
             'nome': forms.TextInput(attrs={'placeholder': 'Ex: Nubank, Visa...'}),
        }

class CategoriaForm(BootstrapModelForm):
    class Meta:
        model = Categoria
        fields = ['nome', 'teto_mensal']
        widgets = {
             'nome': forms.TextInput(attrs={'placeholder': 'Ex: Alimentação, Lazer...'}),
        }

class GastoFixoForm(BootstrapModelForm):
    class Meta:
        model = GastoFixo
        fields = ['nome', 'valor_previsto', 'dia_vencimento', 'categoria', 'eh_cartao', 'cartao']
        widgets = {
             'nome': forms.TextInput(attrs={'placeholder': 'Ex: Netflix, Academia...'}),
             'dia_vencimento': forms.NumberInput(attrs={'max': 31, 'min': 1}),
             'categoria': forms.Select(attrs={'class': 'form-select'}),
             
             # AQUI ESTÁ A MUDANÇA: Adicionamos IDs para o JavaScript usar
             'eh_cartao': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch', 'id': 'check_cartao'}),
             'cartao': forms.Select(attrs={'class': 'form-select', 'id': 'campo_cartao'}),
        }

class SimulacaoForm(forms.Form):
    valor_compra = forms.DecimalField(label="Valor da Compra", widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 2500.00'}))
    parcelas = forms.IntegerField(label="Nº Parcelas", widget=forms.NumberInput(attrs={'class': 'form-control', 'value': 10}))
    inicio_pagamento = forms.DateField(label="1ª Parcela em:", widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}))

# --- SETUP INICIAL ---
class SetupInicialForm(forms.Form):
    saldo_atual = forms.DecimalField(label="Saldo Atual na Conta (R$)", widget=forms.NumberInput(attrs={'class': 'form-control'}))
    
    tem_fatura = forms.BooleanField(label="Tem fatura de cartão em aberto?", required=False, widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'check_fatura'}))
    valor_fatura = forms.DecimalField(label="Valor Total da Fatura de Dezembro/Passada", required=False, widget=forms.NumberInput(attrs={'class': 'form-control'}))
    cartao_fatura = forms.ModelChoiceField(queryset=CartaoCredito.objects.all(), required=False, label="Qual cartão?", widget=forms.Select(attrs={'class': 'form-select'}))

# --- CAIXINHAS ---
class CaixinhaForm(BootstrapModelForm):
    class Meta:
        model = Caixinha
        fields = ['nome', 'saldo_atual', 'meta_cdi']
        widgets = { 'nome': forms.TextInput(attrs={'placeholder': 'Ex: Reserva, Viagem...'}) }

class EmprestimoProprioForm(BootstrapModelForm):
    class Meta:
        model = EmprestimoProprio
        fields = ['caixinha_origem', 'valor_emprestado', 'juros_mensais', 'qtd_parcelas', 'data_inicio']