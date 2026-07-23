from django.contrib import admin
from django.urls import path
from finance import views

urlpatterns = [
    path('admin/', admin.site.urls),

    # --- DASHBOARD E EXTRATO ---
    path('', views.dashboard, name='dashboard'),
    path('extrato/', views.statement, name='extrato'),
    path('extrato/editar/<int:id>/', views.edit_transaction, name='editar_transacao'),
    path('transacao/apagar/<int:id>/', views.delete_transaction, name='apagar_transacao'),
    path('analise-anual/', views.annual_analysis, name='analise_anual'),

    # --- CAIXINHAS E INVESTIMENTOS (O QUE ESTAVA FALTANDO) ---
    path('caixinhas/', views.savings_boxes, name='caixinhas'),
    path('caixinhas/nova/', views.new_savings_box, name='nova_caixinha'),
    path('caixinhas/emprestimo/', views.new_self_loan, name='novo_emprestimo_proprio'),
    path('caixinhas/editar/<int:id>/', views.edit_savings_box, name='editar_caixinha'),
    path('caixinhas/apagar/<int:id>/', views.delete_savings_box, name='apagar_caixinha'),
    path('caixinhas/detalhes/<int:id>/', views.savings_box_detail, name='detalhes_caixinha'),
    path('caixinhas/resgatar/', views.withdraw_savings_box, name='resgatar_caixinha'),

    # --- TRANSAÇÕES (RECEITA E DESPESA) ---
    path('despesa/nova/', views.new_transaction, name='nova_transacao'),
    path('receita/nova/', views.new_income, name='nova_receita'),

    # --- CARTÕES ---
    path('cartoes/', views.manage_credit_cards, name='gerenciar_cartoes'),
    path('cartoes/novo/', views.new_credit_card, name='novo_cartao'),
    path('cartoes/editar/<int:id>/', views.edit_credit_card, name='editar_cartao'),
    path('cartoes/apagar/<int:id>/', views.delete_credit_card, name='apagar_cartao'),

    # --- CATEGORIAS ---
    path('categorias/', views.manage_categories, name='gerenciar_categorias'),
    path('categorias/nova/', views.new_category, name='nova_categoria'),
    path('categorias/guardar-sobra/', views.save_leftover, name='guardar_sobra'),
    path('categorias/editar/<int:id>/', views.edit_category, name='editar_categoria'),
    path('categorias/apagar/<int:id>/', views.delete_category, name='apagar_categoria'),

    # --- GASTOS FIXOS (CONTAS) ---
    path('fixos/', views.manage_fixed_expenses, name='gerenciar_fixos'),
    path('fixos/novo/', views.new_fixed_expense, name='novo_fixo'),
    path('fixos/apagar/<int:id>/', views.delete_fixed_expense, name='apagar_fixo'),
    path('fixos/pagar/<int:id_fixo>/', views.pay_fixed_expense, name='pagar_gasto_fixo'),

    # --- RECEITAS FIXAS (SALÁRIOS) ---
    path('receitas-fixas/', views.manage_fixed_incomes, name='gerenciar_receitas_fixas'),
    path('receitas-fixas/nova/', views.new_fixed_income, name='nova_receita_fixa'),
    path('receitas-fixas/apagar/<int:id>/', views.delete_fixed_income, name='apagar_receita_fixa'),
    path('receita/excluir/<int:id>/', views.delete_income, name='excluir_receita'),
    path('receita/editar/<int:id>/', views.edit_income, name='editar_receita'),
    path('editar-fixo/<int:id>/', views.edit_fixed_expense, name='editar_gasto_fixo'),
    path('excluir-fixo/<int:id>/', views.remove_fixed_expense, name='excluir_gasto_fixo'),

    path('relatorios/categorias/', views.category_report, name='relatorio_categorias'),
    path('relatorios/anual/', views.annual_report, name='relatorio_anual'),
    path('relatorios/categorias/detalhes/<int:categoria_id>/', views.category_expense_detail, name='detalhes_gastos_categoria'),

    path('fatura/pagar/', views.pay_monthly_invoice, name='pagar_fatura_mensal'),

    path('adicionar-conta-avulsa/', views.add_one_off_bill, name='adicionar_conta_avulsa'),
    path('pagar-conta-avulsa/<int:id>/', views.pay_one_off_bill, name='pagar_conta_avulsa'),
    path('apagar-conta-avulsa/<int:id>/', views.delete_one_off_bill, name='apagar_conta_avulsa'),
    path('editar-conta-avulsa/<int:id>/', views.edit_one_off_bill, name='editar_conta_avulsa'),
]
