import json

from .forms import TransactionForm, IncomeForm
from .models import Category
from .services import build_cartoes_json


def quick_add_forms(request):
    """Fresh, empty forms for the '+ Despesa' / '+ Receita' navbar modals, available on
    every page since the navbar itself is rendered on every page"""
    if not request.user.is_authenticated:
        return {}

    reverse_logic_map = {cat.id: cat.reverse_logic for cat in Category.objects.for_user(request.user)}
    return {
        'navbar_expense_form': TransactionForm(auto_id='navbar_expense_%s', user=request.user),
        'navbar_income_form': IncomeForm(auto_id='navbar_income_%s', user=request.user),
        # Lets JS show/hide the "Caixinha de Destino" field by the category's real
        # reverse_logic flag, instead of guessing from the category's name
        'category_reverse_logic_json': json.dumps(reverse_logic_map),
        # Mesma memória de cartões (due_day/closing_day/closed_months) usada na página
        # inteira de "Nova Despesa" - disponível globalmente porque o modal "+ Despesa"
        # da navbar aparece em toda página, não só na tela de new_transaction
        'cartoes_json': build_cartoes_json(request.user),
    }
