from django import forms
from .models import Transaction, Income, CreditCard, Category, FixedExpense, FixedIncome, SavingsBox, OwnedModel, PeriodicPurchase

# Estilo padrão para todos os inputs ficarem bonitos
class BootstrapModelForm(forms.ModelForm):
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            # Checkboxes precisam da classe do Bootstrap pra virar um switch, não uma barra gigante
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'form-check-input'
                field.widget.attrs.setdefault('role', 'switch')
            else:
                field.widget.attrs['class'] = 'form-control form-control-lg'

            # Dropdowns pointing at another user's data (category, target_savings_box,
            # credit_card etc.) must only ever offer THIS user's own records
            if isinstance(field, forms.ModelChoiceField) and issubclass(field.queryset.model, OwnedModel):
                field.queryset = field.queryset.model.objects.for_user(user) if user else field.queryset.none()

class TransactionForm(BootstrapModelForm):
    force_next_invoice = forms.BooleanField(
        required=False,
        initial=False,
        label="💳 A fatura deste cartão já fechou?",
        help_text="Marque só se tiver certeza. Vale pro resto do mês nesse cartão - "
                   "no próximo ciclo a pergunta volta a aparecer.",
    )

    class Meta:
        model = Transaction
        fields = ['description',
                  'total_amount',
                  'category',
                  'target_savings_box',
                  'is_credit_card',
                  'credit_card',
                  'installments_count',
                  'purchase_date',
                  'force_next_invoice']
        widgets = {
            'purchase_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'description': forms.TextInput(attrs={'placeholder': 'Ex: Mercado, Uber...'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'target_savings_box': forms.Select(attrs={'class': 'form-select'}),
            'is_credit_card': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'credit_card': forms.Select(attrs={'class': 'form-select'}),
            'installments_count': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'value': 1}),
            'force_next_invoice': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
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
            'date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
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
             'is_credit_card': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
             'credit_card': forms.Select(attrs={'class': 'form-select'}),
             'target_savings_box': forms.Select(attrs={'class': 'form-select'}),
        }

class PeriodicPurchaseForm(BootstrapModelForm):
    class Meta:
        model = PeriodicPurchase
        fields = ['name', 'estimated_amount', 'interval_months', 'is_automatic', 'last_purchase_date', 'category', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Ex: Perfume, Creme de Cabelo, Hidratante Facial...'}),
            'interval_months': forms.NumberInput(attrs={'min': 1, 'placeholder': 'Ex: 3'}),
            'last_purchase_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.TextInput(attrs={'placeholder': 'Opcional'}),
        }


class SimulationForm(forms.Form):
    valor_compra = forms.DecimalField(label="Valor da Compra", widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 2500.00'}))
    parcelas = forms.IntegerField(label="Nº Parcelas", widget=forms.NumberInput(attrs={'class': 'form-control', 'value': 10}))
    inicio_pagamento = forms.DateField(label="1ª Parcela em:", widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}, format='%Y-%m-%d'))

# --- INITIAL SETUP ---
class InitialSetupForm(forms.Form):
    saldo_atual = forms.DecimalField(label="Saldo Atual na Conta (R$)", widget=forms.NumberInput(attrs={'class': 'form-control'}))

    tem_fatura = forms.BooleanField(label="Tem fatura de cartão em aberto?", required=False, widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'id': 'check_fatura'}))
    valor_fatura = forms.DecimalField(label="Valor Total da Fatura de Dezembro/Passada", required=False, widget=forms.NumberInput(attrs={'class': 'form-control'}))
    cartao_fatura = forms.ModelChoiceField(queryset=CreditCard.objects.none(), required=False, label="Qual cartão?", widget=forms.Select(attrs={'class': 'form-select'}))

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields['cartao_fatura'].queryset = CreditCard.objects.for_user(user)

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

class WithdrawSavingsBoxForm(forms.Form):
    # AQUI ESTÁ O CAMPO QUE ESTAVA FALTANDO APARECER!
    source_savings_box = forms.ModelChoiceField(
        queryset=SavingsBox.objects.none(),
        label='De qual Caixinha?',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    DESTINATION_CHOICES = [
        ('SALDO', 'Resgatar para a Conta (Saldo Livre)'),
        ('DIVIDA', 'Pagar uma Dívida/Despesa Direta'),
    ]

    amount = forms.DecimalField(
        label='Valor do Resgate (R$)',
        max_digits=10, 
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 150.00', 'step': '0.01'})
    )
    
    destination = forms.ChoiceField(
        choices=DESTINATION_CHOICES,
        label='Destino do Dinheiro',
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        initial='SALDO'
    )

    expense_description = forms.CharField(
        label='Descrição da Despesa', 
        max_length=100, 
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Fatura Cartão'})
    )
    
    expense_category = forms.ModelChoiceField(
        queryset=Category.objects.none(), 
        label='Categoria da Despesa',
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            # Preenche as opções do select com as caixinhas e categorias do usuário
            self.fields['expense_category'].queryset = Category.objects.for_user(user)
            self.fields['source_savings_box'].queryset = SavingsBox.objects.for_user(user)

    def clean(self):
        cleaned_data = super().clean()
        destination = cleaned_data.get('destination')
        
        if destination == 'DIVIDA':
            if not cleaned_data.get('expense_description'):
                self.add_error('expense_description', 'Informe a descrição da despesa.')
            if not cleaned_data.get('expense_category'):
                self.add_error('expense_category', 'Selecione uma categoria.')
        return cleaned_data
