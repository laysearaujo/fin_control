from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Sum
from django.utils import timezone
from datetime import date
from dateutil.relativedelta import relativedelta
from .models import Parcela, Receita, GastoFixo, Transacao, Categoria, CartaoCredito, ReceitaFixa, Caixinha, EmprestimoProprio
from .forms import (
    TransacaoForm, ReceitaForm, CartaoForm, CategoriaForm, 
    GastoFixoForm, SimulacaoForm, ReceitaFixaForm,
    SetupInicialForm, CaixinhaForm, EmprestimoProprioForm
)

# --- 1. DASHBOARD PRINCIPAL ---
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Sum
from django.utils import timezone
from datetime import date
from dateutil.relativedelta import relativedelta
from .models import (
    Transacao, Receita, GastoFixo, ReceitaFixa, 
    Parcela, Caixinha, CartaoCredito
)

def dashboard(request):
    # --- DEFINIÇÃO DE DATA ---
    mes_url = request.GET.get('mes')
    ano_url = request.GET.get('ano')
    data_hoje = timezone.now().date()
    
    if mes_url and ano_url:
        data_ref = date(int(ano_url), int(mes_url), 1)
    else:
        data_ref = date(data_hoje.year, data_hoje.month, 1)

    mes_anterior = data_ref - relativedelta(months=1)
    proximo_mes = data_ref + relativedelta(months=1)
    inicio_mes_atual = date(data_hoje.year, data_hoje.month, 1)
    
    eh_passado = data_ref < inicio_mes_atual
    eh_futuro = data_ref > inicio_mes_atual
    eh_corrente = (data_ref == inicio_mes_atual)

    # --- 1. SALDO ANTERIOR ---
    hist_receitas = Receita.objects.filter(data__lt=data_ref).aggregate(Sum('valor'))['valor__sum'] or 0
    hist_despesas = Transacao.objects.filter(eh_cartao=False, data_compra__lt=data_ref).aggregate(Sum('valor_total'))['valor_total__sum'] or 0
    saldo_anterior = hist_receitas - hist_despesas

    # --- 2. FATURA DO CARTÃO DETALHADA ---
    itens_fatura_detalhe = [] # LISTA QUE FALTAVA
    
    # A. Parcelas
    parcelas_fatura = Parcela.objects.filter(
        data_vencimento__month=data_ref.month, 
        data_vencimento__year=data_ref.year
    ).select_related('transacao') # Otimiza o banco
    
    soma_parcelas = parcelas_fatura.aggregate(Sum('valor'))['valor__sum'] or 0
    
    for p in parcelas_fatura:
        itens_fatura_detalhe.append({
            'desc': f"{p.transacao.descricao} ({p.numero_parcela}/{p.transacao.qtd_parcelas})",
            'valor': p.valor,
            'tipo': 'compra'
        })

    # B. Assinaturas
    soma_assinaturas_cartao = 0
    fixos_no_cartao = GastoFixo.objects.filter(eh_cartao=True)
    
    for fixo in fixos_no_cartao:
        ja_lancado = Transacao.objects.filter(
            gasto_fixo=fixo,
            data_compra__month=data_ref.month,
            data_compra__year=data_ref.year
        ).exists()
        
        if not ja_lancado:
            soma_assinaturas_cartao += fixo.valor_previsto
            itens_fatura_detalhe.append({
                'desc': f"{fixo.nome} (Assinatura)",
                'valor': fixo.valor_previsto,
                'tipo': 'fixo'
            })

    total_cartao_mes = soma_parcelas + soma_assinaturas_cartao

    # --- 3. PROJEÇÃO DO MÊS ---
    receita_fixa_total = ReceitaFixa.objects.aggregate(Sum('valor'))['valor__sum'] or 0
    receita_variavel_total = Receita.objects.filter(data__month=data_ref.month, data__year=data_ref.year).aggregate(Sum('valor'))['valor__sum'] or 0
    total_receitas_previsto = receita_fixa_total + receita_variavel_total

    total_fixos_banco = GastoFixo.objects.filter(eh_cartao=False).aggregate(Sum('valor_previsto'))['valor_previsto__sum'] or 0
    gastos_variaveis_avulsos = Transacao.objects.filter(
        eh_cartao=False, 
        gasto_fixo__isnull=True, 
        eh_pagamento_fatura=False, 
        data_compra__month=data_ref.month, 
        data_compra__year=data_ref.year
    ).aggregate(Sum('valor_total'))['valor_total__sum'] or 0
    
    total_saidas_previsto = total_fixos_banco + gastos_variaveis_avulsos + total_cartao_mes
    saldo_projetado = saldo_anterior + total_receitas_previsto - total_saidas_previsto

    # --- 4. SALDO REAL ---
    receitas_reais_mes = Receita.objects.filter(data__month=data_ref.month, data__year=data_ref.year).aggregate(Sum('valor'))['valor__sum'] or 0
    if eh_corrente:
        for r_fixa in ReceitaFixa.objects.all():
            if data_hoje.day >= r_fixa.dia_recebimento:
                receitas_reais_mes += r_fixa.valor
    elif eh_passado:
        receitas_reais_mes += ReceitaFixa.objects.aggregate(Sum('valor'))['valor__sum'] or 0

    saidas_reais_mes = Transacao.objects.filter(
        eh_cartao=False,
        data_compra__month=data_ref.month, 
        data_compra__year=data_ref.year
    ).aggregate(Sum('valor_total'))['valor_total__sum'] or 0
    
    saldo_real_atual = saldo_anterior + receitas_reais_mes - saidas_reais_mes

    # --- 5. DETALHES ---
    lista_fixos_status = []
    total_fixos_pendentes_banco = 0
    for fixo in GastoFixo.objects.all():
        pagamento = Transacao.objects.filter(gasto_fixo=fixo, data_compra__month=data_ref.month, data_compra__year=data_ref.year).first()
        status = 'pago' if pagamento else 'pendente'
        valor_pago = pagamento.valor_total if pagamento else 0
        
        if status == 'pendente' and not fixo.eh_cartao:
            total_fixos_pendentes_banco += fixo.valor_previsto

        lista_fixos_status.append({
            'id': fixo.id, 'nome': fixo.nome, 'status': status, 
            'valor_previsto': fixo.valor_previsto, 'valor_pago': valor_pago, 
            'dia': fixo.dia_vencimento, 'eh_cartao': fixo.eh_cartao
        })

    # --- 6. CHECK DE PAGAMENTO DA FATURA (ESSENCIAL) ---
    fatura_paga = Transacao.objects.filter(
        eh_pagamento_fatura=True,
        data_compra__month=data_ref.month,
        data_compra__year=data_ref.year
    ).exists()

    context = {
        'data_ref': data_ref,
        'eh_passado': eh_passado, 'eh_futuro': eh_futuro, 'eh_corrente': eh_corrente,
        'mes_ant_url': f"?mes={mes_anterior.month}&ano={mes_anterior.year}",
        'prox_mes_url': f"?mes={proximo_mes.month}&ano={proximo_mes.year}",
        'saldo_anterior': saldo_anterior, 'saldo_projetado': saldo_projetado, 'saldo_real_atual': saldo_real_atual,
        'total_receitas_previsto': total_receitas_previsto, 'total_saidas_previsto': total_saidas_previsto,
        'receitas_reais_mes': receitas_reais_mes, 'saidas_reais_mes': saidas_reais_mes,
        'lista_fixos_detalhada': lista_fixos_status, 'total_fixos_pendentes': total_fixos_pendentes_banco,
        'total_cartao': total_cartao_mes,
        'total_investido': Caixinha.objects.aggregate(Sum('saldo_atual'))['saldo_atual__sum'] or 0,
        
        # --- AQUI ESTAVA O ERRO, AGORA ESTÁ CORRIGIDO: ---
        'itens_fatura_detalhe': itens_fatura_detalhe, 
        'fatura_paga': fatura_paga 
    }
    return render(request, 'dashboard.html', context)

# --- CAIXINHAS E EMPRÉSTIMOS ---
def caixinhas(request):
    lista = Caixinha.objects.all()
    total_guardado = lista.aggregate(Sum('saldo_atual'))['saldo_atual__sum'] or 0
    
    # Processa atualização de saldo (Ajuste a Mercado)
    if request.method == 'POST' and 'atualizar_saldo' in request.POST:
        id_cx = request.POST.get('caixinha_id')
        novo_valor = request.POST.get('novo_valor')
        cx = Caixinha.objects.get(id=id_cx)
        cx.saldo_atual = novo_valor
        cx.save()
        return redirect('caixinhas')

    return render(request, 'caixinhas.html', {'caixinhas': lista, 'total': total_guardado})

def nova_caixinha(request):
    form = CaixinhaForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect('caixinhas')
    return render(request, 'form_generico.html', {'form': form, 'titulo': '💰 Nova Caixinha'})

def novo_emprestimo_proprio(request):
    form = EmprestimoProprioForm(request.POST or None)
    if form.is_valid():
        emp = form.save(commit=False)
        caixinha = emp.caixinha_origem
        
        # 1. Tira o dinheiro da caixinha
        if caixinha.saldo_atual < emp.valor_emprestado:
             # Lógica de erro aqui se quiser
             pass
        caixinha.saldo_atual -= emp.valor_emprestado
        caixinha.save()
        
        # 2. Coloca o dinheiro na conta corrente (Receita)
        Receita.objects.create(
            descricao=f"Empréstimo da {caixinha.nome}",
            valor=emp.valor_emprestado,
            data=emp.data_inicio
        )
        
        # 3. Cria a obrigação de pagar (Gasto Fixo Temporário)
        valor_parcela = emp.valor_parcela()
        emp.save() # Salva o empréstimo
        
        GastoFixo.objects.create(
            nome=f"Pagamento Empréstimo ({caixinha.nome})",
            valor_previsto=valor_parcela,
            dia_vencimento=emp.data_inicio.day,
            # Categoria poderia ser "Dívidas"
            emprestimo_vinculado=emp 
        )
        # Obs: A lógica para remover esse Gasto Fixo após N parcelas precisa ser feita no futuro
        
        return redirect('caixinhas')
        
    return render(request, 'form_generico.html', {'form': form, 'titulo': '💸 Empréstimo de Mim Mesmo'})

# --- 2. ANÁLISE ANUAL E SIMULADOR ---
def analise_anual(request):
    hoje = timezone.now().date()
    dados_meses = []
    
    # Lógica do Simulador
    form_simulacao = SimulacaoForm(request.POST or None)
    simulacao_ativa = False
    valor_parcela_simulada = 0
    meses_simulados = []

    if request.method == 'POST' and form_simulacao.is_valid():
        simulacao_ativa = True
        v_total = form_simulacao.cleaned_data['valor_compra']
        qtd_p = form_simulacao.cleaned_data['parcelas']
        data_inicio = form_simulacao.cleaned_data['inicio_pagamento']
        
        valor_parcela_simulada = v_total / qtd_p
        for i in range(qtd_p):
            meses_simulados.append(data_inicio + relativedelta(months=i))

    # Valores Fixos Totais (para não consultar banco dentro do loop)
    total_receita_fixa = ReceitaFixa.objects.aggregate(Sum('valor'))['valor__sum'] or 0
    total_gasto_fixo = GastoFixo.objects.aggregate(Sum('valor_previsto'))['valor_previsto__sum'] or 0

    # Loop Próximos 12 Meses
    for i in range(12):
        data_ref = hoje + relativedelta(months=i)
        
        # Receita Extra do mês (ex: 13º)
        receita_extra = Receita.objects.filter(
            data__month=data_ref.month, 
            data__year=data_ref.year
        ).aggregate(Sum('valor'))['valor__sum'] or 0
        
        receita_total = total_receita_fixa + receita_extra
        
        # Parcelas Reais já existentes
        parcelas_reais = Parcela.objects.filter(
            data_vencimento__month=data_ref.month, 
            data_vencimento__year=data_ref.year
        ).aggregate(Sum('valor'))['valor__sum'] or 0
        
        comprometido = total_gasto_fixo + parcelas_reais
        
        # Custo da Simulação
        custo_extra_simulacao = 0
        if simulacao_ativa:
            for m_sim in meses_simulados:
                if m_sim.month == data_ref.month and m_sim.year == data_ref.year:
                    custo_extra_simulacao = valor_parcela_simulada
                    break
        
        saldo_final = receita_total - (comprometido + custo_extra_simulacao)

        dados_meses.append({
            'mes_nome': data_ref.strftime("%b/%Y"),
            'receita': float(receita_total),
            'comprometido_real': float(comprometido),
            'simulacao': float(custo_extra_simulacao),
            'saldo': float(saldo_final),
            'alerta': saldo_final < 0
        })

    # Dados para o Gráfico Chart.js
    labels = [d['mes_nome'] for d in dados_meses]
    data_receita = [d['receita'] for d in dados_meses]
    data_real = [d['comprometido_real'] for d in dados_meses]
    data_simulacao = [d['simulacao'] for d in dados_meses]

    return render(request, 'analise_anual.html', {
        'form': form_simulacao,
        'tabela': dados_meses,
        'labels': labels,
        'data_receita': data_receita,
        'data_real': data_real,
        'data_simulacao': data_simulacao,
        'simulacao_ativa': simulacao_ativa
    })

# --- 3. TRANSAÇÕES (DESPESAS E EXTRAS) ---

def nova_transacao(request):
    form = TransacaoForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect('dashboard')
    return render(request, 'form_generico.html', {'form': form, 'titulo': '💸 Nova Despesa'})

def nova_receita(request):
    """Para receitas variáveis (freelas, vendas, bônus)"""
    form = ReceitaForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect('dashboard')
    return render(request, 'form_generico.html', {'form': form, 'titulo': '💰 Nova Entrada Extra'})

# --- 4. GERENCIAMENTO DE CARTÕES ---

def gerenciar_cartoes(request):
    cartoes = CartaoCredito.objects.all()
    return render(request, 'lista_cartoes.html', {'cartoes': cartoes})

def novo_cartao(request):
    form = CartaoForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect('gerenciar_cartoes')
    return render(request, 'form_generico.html', {'form': form, 'titulo': '💳 Novo Cartão'})

# --- 5. GERENCIAMENTO DE CATEGORIAS ---

def gerenciar_categorias(request):
    categorias = Categoria.objects.all()
    return render(request, 'lista_categorias.html', {'categorias': categorias})

def nova_categoria(request):
    form = CategoriaForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect('gerenciar_categorias')
    return render(request, 'form_generico.html', {'form': form, 'titulo': '📂 Nova Categoria'})

# --- 6. GERENCIAMENTO DE GASTOS FIXOS (ALUGUEL/LUZ) ---

def gerenciar_fixos(request):
    fixos = GastoFixo.objects.all()
    return render(request, 'lista_fixos.html', {'fixos': fixos})

def novo_fixo(request):
    form = GastoFixoForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect('gerenciar_fixos')
    return render(request, 'form_generico.html', {'form': form, 'titulo': '🏠 Novo Gasto Recorrente'})

def apagar_fixo(request, id):
    item = get_object_or_404(GastoFixo, id=id)
    item.delete()
    return redirect('gerenciar_fixos')

# --- 7. GERENCIAMENTO DE RECEITAS FIXAS (SALÁRIO) ---

def gerenciar_receitas_fixas(request):
    fixas = ReceitaFixa.objects.all()
    return render(request, 'lista_receitas_fixas.html', {'fixas': fixas})

def nova_receita_fixa(request):
    form = ReceitaFixaForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect('gerenciar_receitas_fixas')
    return render(request, 'form_generico.html', {'form': form, 'titulo': '💰 Novo Salário Fixo'})

def apagar_receita_fixa(request, id):
    item = get_object_or_404(ReceitaFixa, id=id)
    item.delete()
    return redirect('gerenciar_receitas_fixas')

def pagar_gasto_fixo(request, id_fixo):
    gasto_fixo = get_object_or_404(GastoFixo, id=id_fixo)
    mes = request.GET.get('mes', timezone.now().month)
    ano = request.GET.get('ano', timezone.now().year)
    
    if request.method == 'POST':
        valor_real = request.POST.get('valor_real')
        data_pagamento = request.POST.get('data_pagamento')
        
        # LÓGICA NOVA AQUI:
        # Se o gasto fixo está configurado como cartão, usamos o cartão dele.
        usar_cartao = gasto_fixo.eh_cartao
        cartao_escolhido = gasto_fixo.cartao if usar_cartao else None
        
        Transacao.objects.create(
            descricao=f"Pgto: {gasto_fixo.nome}",
            valor_total=valor_real,
            data_compra=data_pagamento,
            gasto_fixo=gasto_fixo,
            categoria=gasto_fixo.categoria,
            
            # Aqui definimos se vai pra fatura ou pro saldo
            eh_cartao=usar_cartao,
            cartao=cartao_escolhido,
            qtd_parcelas=1 # Assinatura mensal é sempre 1x
        )
        
        return redirect(f'/?mes={mes}&ano={ano}')

    return render(request, 'pagar_fixo.html', {
        'fixo': gasto_fixo, 
        'mes': mes, 
        'ano': ano,
        'valor_sugerido': gasto_fixo.valor_previsto
    })

def extrato(request):
    """Lista todas as transações para auditoria"""
    transacoes = Transacao.objects.all().order_by('-data_compra')
    return render(request, 'extrato.html', {'transacoes': transacoes})

def apagar_transacao(request, id):
    """Permite excluir um lançamento errado"""
    transacao = get_object_or_404(Transacao, id=id)
    transacao.delete()
    return redirect(request.META.get('HTTP_REFERER', '/'))

def relatorio_categorias(request):
    """Gera dados para o gráfico de pizza"""
    # Define o mês (Padrão: Atual)
    mes = int(request.GET.get('mes', timezone.now().month))
    ano = int(request.GET.get('ano', timezone.now().year))
    
    # 1. Gastos via Débito/Dinheiro (Transacoes normais)
    gastos_avulsos = Transacao.objects.filter(
        eh_cartao=False, 
        data_compra__month=mes, 
        data_compra__year=ano
    ).values('categoria__nome').annotate(total=Sum('valor_total'))

    # 2. Gastos via Cartão (Parcelas que caem neste mês)
    # Aqui precisamos fazer uma 'mágica' para pegar a categoria da transação original
    parcelas = Parcela.objects.filter(
        data_vencimento__month=mes,
        data_vencimento__year=ano
    ).select_related('transacao__categoria')

    # Agrupar parcelas manualmente (Python) pois o GroupBy via ORM fica complexo aqui
    dados_finais = {} # Ex: {'Mercado': 500, 'Lazer': 200}

    # Soma os avulsos
    for g in gastos_avulsos:
        nome = g['categoria__nome'] or 'Sem Categoria'
        dados_finais[nome] = dados_finais.get(nome, 0) + float(g['total'])

    # Soma as parcelas de cartão
    for p in parcelas:
        nome = p.transacao.categoria.nome if p.transacao.categoria else 'Sem Categoria'
        dados_finais[nome] = dados_finais.get(nome, 0) + float(p.valor)

    # Prepara para o Chart.js
    labels = list(dados_finais.keys())
    valores = list(dados_finais.values())

    return render(request, 'relatorio_categorias.html', {
        'mes': mes, 'ano': ano,
        'labels': labels, 
        'data': valores
    })

def relatorio_anual(request):
    """Gera o Semáforo (Verde/Vermelho) para os 12 meses"""
    ano = int(request.GET.get('ano', timezone.now().year))
    hoje = timezone.now().date()
    
    grid_meses = []
    
    # Prepara totais fixos para não consultar banco 12x
    receita_fixa_total = ReceitaFixa.objects.aggregate(Sum('valor'))['valor__sum'] or 0
    gasto_fixo_total = GastoFixo.objects.aggregate(Sum('valor_previsto'))['valor_previsto__sum'] or 0

    for i in range(1, 13):
        data_ref = date(ano, i, 1)
        eh_passado = data_ref < date(hoje.year, hoje.month, 1)
        
        # Receitas
        receita_extra = Receita.objects.filter(data__month=i, data__year=ano).aggregate(Sum('valor'))['valor__sum'] or 0
        total_receitas = receita_fixa_total + receita_extra
        
        # Despesas
        parcelas = Parcela.objects.filter(data_vencimento__month=i, data_vencimento__year=ano).aggregate(Sum('valor'))['valor__sum'] or 0
        avulsos = 0
        
        if eh_passado:
            # Se for passado, pega o realizado REAL
            avulsos = Transacao.objects.filter(eh_cartao=False, data_compra__month=i, data_compra__year=ano).aggregate(Sum('valor_total'))['valor_total__sum'] or 0
            # No passado, o 'gasto_fixo_total' é substituído pelos pagamentos reais (que estão em 'avulsos')
            # Então para simplificar o passado: Receita Real - Saída Real
            receitas_reais = Receita.objects.filter(data__month=i, data__year=ano).aggregate(Sum('valor'))['valor__sum'] or 0 
            # (Adicione salários fixos ao passado se quiser precisão histórica, mas vamos simplificar)
            
            saldo = (receita_fixa_total + receitas_reais) - (avulsos + parcelas) # Aproximação
        else:
            # Futuro: Previsão
            # Avulsos futuros não existem ainda, então usamos Fixos + Parcelas
            saldo = total_receitas - (gasto_fixo_total + parcelas)

        grid_meses.append({
            'mes_num': i,
            'mes_nome': data_ref.strftime('%B'), # Nome do mês
            'saldo': saldo,
            'cor': 'success' if saldo >= 0 else 'danger', # Verde ou Vermelho
            'passado': eh_passado
        })

    return render(request, 'relatorio_anual.html', {'ano': ano, 'grid': grid_meses})

def pagar_fatura_mensal(request):
    """Gera uma transação de saída para quitar a fatura do mês selecionado"""
    mes = int(request.GET.get('mes', timezone.now().month))
    ano = int(request.GET.get('ano', timezone.now().year))
    
    # 1. Calcula o valor total da fatura daquele mês
    total_fatura = Parcela.objects.filter(
        data_vencimento__month=mes,
        data_vencimento__year=ano
    ).aggregate(Sum('valor'))['valor__sum'] or 0
    
    if total_fatura > 0:
        # 2. Cria a transação de pagamento
        Transacao.objects.create(
            descricao=f"Pgto Fatura Cartão ({mes}/{ano})",
            valor_total=total_fatura,
            data_compra=timezone.now().date(), # Sai dinheiro hoje
            eh_cartao=False, # É dinheiro/débito
            eh_pagamento_fatura=True # IMPORTANTE: Marca para não duplicar na previsão
        )
    
    return redirect(request.META.get('HTTP_REFERER', '/'))
