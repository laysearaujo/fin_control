from django.contrib import admin
from django.urls import path
from finance import views

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # --- DASHBOARD E EXTRATO ---
    path('', views.dashboard, name='dashboard'),
    path('extrato/', views.extrato, name='extrato'),
    path('transacao/apagar/<int:id>/', views.apagar_transacao, name='apagar_transacao'),
    path('analise-anual/', views.analise_anual, name='analise_anual'),

    # --- CAIXINHAS E INVESTIMENTOS (O QUE ESTAVA FALTANDO) ---
    path('caixinhas/', views.caixinhas, name='caixinhas'),
    path('caixinhas/nova/', views.nova_caixinha, name='nova_caixinha'),
    path('caixinhas/emprestimo/', views.novo_emprestimo_proprio, name='novo_emprestimo_proprio'),

    # --- TRANSAÇÕES (RECEITA E DESPESA) ---
    path('despesa/nova/', views.nova_transacao, name='nova_transacao'),
    path('receita/nova/', views.nova_receita, name='nova_receita'),
    
    # --- CARTÕES ---
    path('cartoes/', views.gerenciar_cartoes, name='gerenciar_cartoes'),
    path('cartoes/novo/', views.novo_cartao, name='novo_cartao'),
    
    # --- CATEGORIAS ---
    path('categorias/', views.gerenciar_categorias, name='gerenciar_categorias'),
    path('categorias/nova/', views.nova_categoria, name='nova_categoria'),

    # --- GASTOS FIXOS (CONTAS) ---
    path('fixos/', views.gerenciar_fixos, name='gerenciar_fixos'),
    path('fixos/novo/', views.novo_fixo, name='novo_fixo'),
    path('fixos/apagar/<int:id>/', views.apagar_fixo, name='apagar_fixo'),
    path('fixos/pagar/<int:id_fixo>/', views.pagar_gasto_fixo, name='pagar_gasto_fixo'),

    # --- RECEITAS FIXAS (SALÁRIOS) ---
    path('receitas-fixas/', views.gerenciar_receitas_fixas, name='gerenciar_receitas_fixas'),
    path('receitas-fixas/nova/', views.nova_receita_fixa, name='nova_receita_fixa'),
    path('receitas-fixas/apagar/<int:id>/', views.apagar_receita_fixa, name='apagar_receita_fixa'),

    path('relatorios/categorias/', views.relatorio_categorias, name='relatorio_categorias'),
    path('relatorios/anual/', views.relatorio_anual, name='relatorio_anual'),

    path('fatura/pagar/', views.pagar_fatura_mensal, name='pagar_fatura_mensal'),
]