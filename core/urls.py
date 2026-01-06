from django.contrib import admin
from django.urls import path
from finance import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.dashboard, name='dashboard'),
    
    # Rotas Novas
    path('despesa/nova/', views.nova_transacao, name='nova_transacao'),
    path('receita/nova/', views.nova_receita, name='nova_receita'),
    
    path('cartoes/', views.gerenciar_cartoes, name='gerenciar_cartoes'),
    path('cartoes/novo/', views.novo_cartao, name='novo_cartao'),
    
    path('categorias/', views.gerenciar_categorias, name='gerenciar_categorias'),
    path('categorias/nova/', views.nova_categoria, name='nova_categoria'),
]