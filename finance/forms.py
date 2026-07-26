from django import forms
from .models import Transaction, Income, CreditCard, Category, FixedExpense, FixedIncome, SavingsBox, SelfLoan

# Estilo padrão para todos os inputs ficarem bonitos
class BootstrapModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            # Checkboxes precisam da classe do Bootstrap pra virar um switch, não uma barra gigante
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'form-check-input'
                field.widget.attrs.setdefault('role', 'switch')
            else:
                field.widget.attrs['class'] = 'form-control form-control-lg'

class TransactionForm(BootstrapModelForm):
    class Meta:
        model = Transaction
        fields = ['description', 'total_amount', 'category', 'target_savings_box', 'is_credit_card', 'credit_card', 'installments_count', 'purchase_date']
        widgets = {
            'purchase_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.TextInput(attrs={'placeholder': 'Ex: Mercado, Uber...'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'target_savings_box': forms.Select(attrs={'class': 'form-select'}),
            'is_credit_card': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch', 'id': 'check_cartao'}),
            'credit_card': forms.Select(attrs={'class': 'form-select'}),
            'installments_count': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'value': 1}),
        }

class FixedIncomeForm(BootstrapModelForm):
    class Meta:
        model = FixedIncome
        fields = ['description', 'amount', 'payment_day']
        widgets = {
             'description': forms.TextInput(attrs={'placeholder': 'Ex: Salário Mensal, Aluguel...'}),
             'payment_day': forms.NumberInput(attrs={'max': 31, 'min': 1}),
        }

class IncomeForm(BootstrapModelForm):
    class Meta:
        model = Income
        fields = ['description', 'amount', 'date']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

class CreditCardForm(BootstrapModelForm):
    class Meta:
        model = CreditCard
        fields = ['name', 'limit', 'closing_day', 'due_day']
        widgets = {
             'name': forms.TextInput(attrs={'placeholder': 'Ex: Nubank, Visa...'}),
        }

class CategoryForm(BootstrapModelForm):
    class Meta:
        model = Category
        fields = ['name', 'monthly_cap', 'reverse_logic']
        widgets = {
             'name': forms.TextInput(attrs={'placeholder': 'Ex: Alimentação, Lazer...'}),
        }

class FixedExpenseForm(BootstrapModelForm):
    class Meta:
        model = FixedExpense
        fields = ['name', 'expected_amount', 'due_day', 'category', 'is_credit_card', 'credit_card', 'target_savings_box']
        widgets = {
             'name': forms.TextInput(attrs={'placeholder': 'Ex: Netflix, Academia...'}),
             'due_day': forms.NumberInput(attrs={'max': 31, 'min': 1}),
             'category': forms.Select(attrs={'class': 'form-select'}),
             'is_credit_card': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch', 'id': 'check_cartao'}),
             'credit_card': forms.Select(attrs={'class': 'form-select', 'id': 'campo_cartao'}),
             'target_savings_box': forms.Select(attrs={'class': 'form-select'}),
        }

class SimulationForm(forms.Form):
    valor_compra = forms.DecimalField(label="Valor da Compra", widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 2500.00'}))
    parcelas = forms.IntegerField(label="Nº Parcelas", widget=forms.NumberInput(attrs={'class': 'form-control', 'value': 10}))
    inicio_pagamento = forms.DateField(label="1ª Parcela em:", widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}))

# --- INITIAL SETUP ---
class InitialSetupForm(forms.Form):
    saldo_atual = forms.DecimalField(label="Saldo Atual na Conta (R$)", widget=forms.NumberInput(attrs={'class': 'form-control'}))

    tem_fatura = forms.BooleanField(label="Tem fatura de cartão em aberto?", required=False, widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'check_fatura'}))
    valor_fatura = forms.DecimalField(label="Valor Total da Fatura de Dezembro/Passada", required=False, widget=forms.NumberInput(attrs={'class': 'form-control'}))
    cartao_fatura = forms.ModelChoiceField(queryset=CreditCard.objects.all(), required=False, label="Qual cartão?", widget=forms.Select(attrs={'class': 'form-select'}))

# --- SAVINGS BOXES ---
class SavingsBoxForm(BootstrapModelForm):
    class Meta:
        model = SavingsBox
        fields = ['name', 'description', 'current_balance', 'cdi_target_pct', 'target_amount', 'is_emergency_reserve']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Ex: Reserva, Viagem...'}),
            'target_amount': forms.NumberInput(attrs={'placeholder': 'Ex: 1500.00 (Opcional)', 'step': '0.01'}),
            'description': forms.Textarea(attrs={'placeholder': 'Escreva aqui o objetivo ou regras dessa caixinha...', 'rows': 3}),
            'is_emergency_reserve': forms.CheckboxInput(attrs={'role': 'switch'}),
        }


class SavingsBoxEditForm(SavingsBoxForm):
    """Same as SavingsBoxForm, minus current_balance - editing settings shouldn't silently
    change the balance without logging it as yield, that only happens via 'Atualizar valor hoje'"""
    class Meta(SavingsBoxForm.Meta):
        fields = ['name', 'description', 'cdi_target_pct', 'target_amount', 'is_emergency_reserve']

class SelfLoanForm(BootstrapModelForm):
    class Meta:
        model = SelfLoan
        fields = ['source_savings_box', 'borrowed_amount', 'monthly_interest_pct', 'installments_count', 'start_date']
