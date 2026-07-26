import json

from .forms import TransactionForm, IncomeForm
from .models import Category


def quick_add_forms(request):
    """Fresh, empty forms for the '+ Despesa' / '+ Receita' navbar modals, available on
    every page since the navbar itself is rendered on every page"""
    reverse_logic_map = {cat.id: cat.reverse_logic for cat in Category.objects.all()}
    return {
        'navbar_expense_form': TransactionForm(auto_id='navbar_expense_%s'),
        'navbar_income_form': IncomeForm(auto_id='navbar_income_%s'),
        # Lets JS show/hide the "Caixinha de Destino" field by the category's real
        # reverse_logic flag, instead of guessing from the category's name
        'category_reverse_logic_json': json.dumps(reverse_logic_map),
    }
