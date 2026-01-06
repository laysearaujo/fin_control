from django import forms
from .models import Transacao, Receita, CartaoCredito, Categoria

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