from django.shortcuts import render, redirect
from django.db.models import Sum
from django.utils import timezone
from .models import Parcela, Receita, GastoFixo, Transacao, Categoria, CartaoCredito
from .forms import TransacaoForm, ReceitaForm, CartaoForm, CategoriaForm

# --- DASHBOARD (Mantivemos igual) ---
def dashboard(request):
    hoje = timezone.now()
    mes_atual = hoje.month
    
    # Cálculos básicos
    total_receitas = Receita.objects.filter(data__month=mes_atual).aggregate(Sum('valor'))['valor__sum'] or 0
    total_saidas = (GastoFixo.objects.aggregate(Sum('valor_previsto'))['valor_previsto__sum'] or 0) + \
                   (Parcela.objects.filter(data_vencimento__month=mes_atual).aggregate(Sum('valor'))['valor__sum'] or 0) + \
                   (Transacao.objects.filter(eh_cartao=False, data_compra__month=mes_atual).aggregate(Sum('valor_total'))['valor_total__sum'] or 0)
    
    saldo = total_receitas - total_saidas
    
    # Pega parcelas futuras para exibir na home
    proximas_contas = Parcela.objects.filter(data_vencimento__gte=hoje, pago=False).order_by('data_vencimento')[:5]

    return render(request, 'dashboard.html', {
        'saldo': saldo, 'total_receitas': total_receitas, 'total_saidas': total_saidas, 
        'proximas_contas': proximas_contas
    })

# --- NOVAS VIEWS ---

def nova_transacao(request):
    form = TransacaoForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect('/') # Volta pra home
    return render(request, 'form_generico.html', {'form': form, 'titulo': '💸 Nova Despesa'})

def nova_receita(request):
    form = ReceitaForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect('/')
    return render(request, 'form_generico.html', {'form': form, 'titulo': '💰 Nova Receita'})

def gerenciar_cartoes(request):
    cartoes = CartaoCredito.objects.all()
    return render(request, 'lista_cartoes.html', {'cartoes': cartoes})

def novo_cartao(request):
    form = CartaoForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect('gerenciar_cartoes')
    return render(request, 'form_generico.html', {'form': form, 'titulo': '💳 Novo Cartão'})

def gerenciar_categorias(request):
    categorias = Categoria.objects.all()
    return render(request, 'lista_categorias.html', {'categorias': categorias})

def nova_categoria(request):
    form = CategoriaForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect('gerenciar_categorias')
    return render(request, 'form_generico.html', {'form': form, 'titulo': '📂 Nova Categoria'})