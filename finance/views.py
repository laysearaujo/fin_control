from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Sum
from django.db import transaction
from django.utils import timezone
from django.contrib import messages
from django.db.models import Q
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from decimal import Decimal

from .models import (
    Parcela, Receita, GastoFixo, Transacao, Categoria, 
    CartaoCredito, ReceitaFixa, Caixinha, EmprestimoProprio, ContaAvulsa
)
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
    # --- DEFINIÇÃO DE DATAS ---
    mes_url = request.GET.get('mes')
    ano_url = request.GET.get('ano')
    data_hoje = timezone.now().date()
    
    try:
        if mes_url and ano_url:
            mes_int = int(mes_url)
            ano_int = int(ano_url)
            
            # Correção automática para virada de ano (Mês 13 vira 1 do ano seguinte, Mês 0 vira 12 do ano anterior)
            if mes_int > 12:
                mes_int = 1
                ano_int += 1
            elif mes_int < 1:
                mes_int = 12
                ano_int -= 1
                
            data_ref = date(ano_int, mes_int, 1)
        else:
            data_ref = date(data_hoje.year, data_hoje.month, 1)
            
    except (ValueError, TypeError):
        # Se vier texto ou vazio na URL, protege o sistema carregando o mês atual
        data_ref = date(data_hoje.year, data_hoje.month, 1)

    mes_anterior = data_ref - relativedelta(months=1)
    proximo_mes = data_ref + relativedelta(months=1)
    
    inicio_mes_atual_real = date(data_hoje.year, data_hoje.month, 1)
    
    eh_passado = data_ref < inicio_mes_atual_real
    eh_futuro = data_ref > inicio_mes_atual_real
    eh_corrente = (data_ref == inicio_mes_atual_real)

    # =========================================================================
    # 1. CÁLCULO DA BASE (PREVISÃO DO MÊS ATUAL)
    # =========================================================================
    
    # A. Saldo Real HOJE
    r_hoje = Receita.objects.filter(data__lte=data_hoje).aggregate(Sum('valor'))['valor__sum'] or 0
    d_hoje = Transacao.objects.filter(eh_cartao=False, data_compra__lte=data_hoje).aggregate(Sum('valor_total'))['valor_total__sum'] or 0
    saldo_base = r_hoje - d_hoje

    # B. Pendências do Mês Atual (Janeiro)
    # Receitas
    for r_fixa in ReceitaFixa.objects.all():
        ja_recebeu = Receita.objects.filter(descricao=r_fixa.descricao, data__month=data_hoje.month, data__year=data_hoje.year).exists()
        if not ja_recebeu:
            saldo_base += r_fixa.valor
            
    # Despesas Fixas Banco
    for fixo in GastoFixo.objects.filter(eh_cartao=False):
        pago = Transacao.objects.filter(gasto_fixo=fixo, data_compra__month=data_hoje.month, data_compra__year=data_hoje.year).exists()
        if not pago:
            saldo_base -= fixo.valor_previsto

    # [NOVO] Contas Avulsas do Mês Atual
    avulsas_hoje = ContaAvulsa.objects.filter(data_vencimento__month=data_hoje.month, data_vencimento__year=data_hoje.year)
    for avulsa in avulsas_hoje:
        # Verifica se pagou buscando pelo vínculo ou descrição/valor
        pago = Transacao.objects.filter(conta_avulsa=avulsa).exists()
        if not pago:
            saldo_base -= avulsa.valor
            
    # Fatura Cartão Janeiro
    desc_fat_atual = f"Pgto Fatura Cartão ({data_hoje.month}/{data_hoje.year})"
    if not Transacao.objects.filter(eh_pagamento_fatura=True, descricao=desc_fat_atual).exists():
        soma_parc = Parcela.objects.filter(data_vencimento__month=data_hoje.month, data_vencimento__year=data_hoje.year).aggregate(Sum('valor'))['valor__sum'] or 0
        soma_assin = 0
        for f in GastoFixo.objects.filter(eh_cartao=True):
            if not Transacao.objects.filter(gasto_fixo=f, data_compra__month=data_hoje.month, data_compra__year=data_hoje.year).exists():
                soma_assin += f.valor_previsto
        saldo_base -= (soma_parc + soma_assin)

    # =========================================================================
    # 2. DEFINIÇÃO DO SALDO ANTERIOR (COM LOOP CASCATA)
    # =========================================================================
    
    if eh_futuro:
        saldo_acumulado = saldo_base 
        mes_iteracao = inicio_mes_atual_real + relativedelta(months=1)
        
        while mes_iteracao < data_ref:
            # Receitas
            receitas_mes = ReceitaFixa.objects.aggregate(Sum('valor'))['valor__sum'] or 0
            
            # Gastos Fixos
            gastos_banco_mes = GastoFixo.objects.filter(eh_cartao=False).aggregate(Sum('valor_previsto'))['valor_previsto__sum'] or 0
            
            # [NOVO] Contas Avulsas do Mês Intermediário
            avulsas_mes = ContaAvulsa.objects.filter(data_vencimento__month=mes_iteracao.month, data_vencimento__year=mes_iteracao.year).aggregate(Sum('valor'))['valor__sum'] or 0

            # Fatura Estimada
            parcelas_mes = Parcela.objects.filter(data_vencimento__month=mes_iteracao.month, data_vencimento__year=mes_iteracao.year).aggregate(Sum('valor'))['valor__sum'] or 0
            assinaturas_mes = GastoFixo.objects.filter(eh_cartao=True).aggregate(Sum('valor_previsto'))['valor_previsto__sum'] or 0
            fatura_mes = parcelas_mes + assinaturas_mes
            
            # Soma Líquida (Incluindo Avulsas)
            saldo_liquido_mes = receitas_mes - (gastos_banco_mes + avulsas_mes + fatura_mes)
            
            saldo_acumulado += saldo_liquido_mes
            mes_iteracao += relativedelta(months=1)
            
        saldo_anterior = saldo_acumulado

    else:
        hist_r = Receita.objects.filter(data__lt=data_ref).aggregate(Sum('valor'))['valor__sum'] or 0
        hist_d = Transacao.objects.filter(eh_cartao=False, data_compra__lt=data_ref).aggregate(Sum('valor_total'))['valor_total__sum'] or 0
        saldo_anterior = hist_r - hist_d

    # =========================================================================
    # 3. DADOS DA TELA
    # =========================================================================
    
    # Fatura Cartão
    itens_fatura_detalhe = [] 
    parcelas_fatura = Parcela.objects.filter(data_vencimento__month=data_ref.month, data_vencimento__year=data_ref.year).select_related('transacao')
    soma_parcelas = parcelas_fatura.aggregate(Sum('valor'))['valor__sum'] or 0
    for p in parcelas_fatura:
        itens_fatura_detalhe.append({'desc': f"{p.transacao.descricao} ({p.numero_parcela}/{p.transacao.qtd_parcelas})", 'valor': p.valor, 'tipo': 'compra'})

    soma_assinaturas_cartao = 0
    fixos_no_cartao = GastoFixo.objects.filter(eh_cartao=True)
    for fixo in fixos_no_cartao:
        ja_lancado = Transacao.objects.filter(gasto_fixo=fixo, data_compra__month=data_ref.month, data_compra__year=data_ref.year).exists()
        if not ja_lancado:
            soma_assinaturas_cartao += fixo.valor_previsto
            itens_fatura_detalhe.append({'desc': f"{fixo.nome} (Assinatura)", 'valor': fixo.valor_previsto, 'tipo': 'fixo'})

    total_cartao_mes = soma_parcelas + soma_assinaturas_cartao

    # A previsão base é apenas o seu Salário Fixo
    receita_fixa_total = ReceitaFixa.objects.aggregate(Sum('valor'))['valor__sum'] or 0
    total_receitas_previsto = receita_fixa_total 
    
    # 1. Receitas Reais (Busca APENAS o que foi realmente recebido e salvo no banco)
    receitas_reais_mes = Receita.objects.filter(data__month=data_ref.month, data__year=data_ref.year).aggregate(Sum('valor'))['valor__sum'] or 0
    
    # 2. Saídas Reais 
    saidas_reais_mes = Transacao.objects.filter(eh_cartao=False, data_compra__month=data_ref.month, data_compra__year=data_ref.year).aggregate(Sum('valor_total'))['valor_total__sum'] or 0
    
    # Ajusta a projeção caso você ganhe um dinheiro extra no mês (além do fixo)
    falta_entrar = total_receitas_previsto - receitas_reais_mes
    if falta_entrar < 0: 
        falta_entrar = 0 
        total_receitas_previsto = receitas_reais_mes # O previsto se ajusta à realidade positiva
    
    # 3. Calcula o Fechamento
    if eh_futuro:
        saldo_real_atual = saldo_anterior 
    else:
        saldo_real_atual = saldo_anterior + receitas_reais_mes - saidas_reais_mes

    # =========================================================================
    # 4. LISTA DE CONTAS (MISTURA FIXO E AVULSO)
    # =========================================================================
    lista_fixos_status = []
    total_pendentes_banco = 0 # Variável unificada
    
    # A. Gastos Fixos
    for fixo in GastoFixo.objects.all():
        pagamento = Transacao.objects.filter(gasto_fixo=fixo, data_compra__month=data_ref.month, data_compra__year=data_ref.year).first()
        status = 'pago' if pagamento else 'pendente'
        valor_pago = pagamento.valor_total if pagamento else 0
        if status == 'pendente' and not fixo.eh_cartao:
            total_pendentes_banco += fixo.valor_previsto
        
        lista_fixos_status.append({
            'id': fixo.id, 'nome': fixo.nome, 'status': status, 
            'valor_previsto': fixo.valor_previsto, 'valor_pago': valor_pago, 
            'dia': fixo.dia_vencimento, 'eh_cartao': fixo.eh_cartao, 'tipo': 'fixo'
        })

    # [NOVO] B. Contas Avulsas (Só deste mês)
    avulsas_tela = ContaAvulsa.objects.filter(data_vencimento__month=data_ref.month, data_vencimento__year=data_ref.year)
    for avulsa in avulsas_tela:
        pagamento = Transacao.objects.filter(conta_avulsa=avulsa).first()
        status = 'pago' if pagamento else 'pendente'
        
        if status == 'pendente':
            total_pendentes_banco += avulsa.valor
            
        lista_fixos_status.append({
            'id': avulsa.id, 'nome': avulsa.titulo, 'status': status,
            'valor_previsto': avulsa.valor, 'valor_pago': avulsa.valor if status == 'pago' else 0,
            'dia': avulsa.data_vencimento.day, 'eh_cartao': False, 'tipo': 'avulsa'
        })

    # Totais Finais
    desc_busca = f"Pgto Fatura Cartão ({data_ref.month}/{data_ref.year})"
    fatura_paga = Transacao.objects.filter(eh_pagamento_fatura=True, descricao=desc_busca).exists()

    valor_fatura_pendente = 0 if fatura_paga else total_cartao_mes
    total_restante_a_pagar = total_pendentes_banco + valor_fatura_pendente

    falta_entrar = total_receitas_previsto - receitas_reais_mes
    if falta_entrar < 0: falta_entrar = 0 

    saldo_projetado = saldo_real_atual + falta_entrar - total_restante_a_pagar
    total_saidas_previsto = saidas_reais_mes + total_restante_a_pagar

    context = {
        'data_ref': data_ref,
        'eh_passado': eh_passado, 'eh_futuro': eh_futuro, 'eh_corrente': eh_corrente,
        'mes_ant_url': f"?mes={mes_anterior.month}&ano={mes_anterior.year}",
        'prox_mes_url': f"?mes={proximo_mes.month}&ano={proximo_mes.year}",
        'saldo_anterior': saldo_anterior, 
        'saldo_real_atual': saldo_real_atual,
        'saldo_projetado': saldo_projetado,
        'total_receitas_previsto': total_receitas_previsto, 
        'total_saidas_previsto': total_saidas_previsto,
        'receitas_reais_mes': receitas_reais_mes, 
        'saidas_reais_mes': saidas_reais_mes,
        'lista_fixos_detalhada': lista_fixos_status, 
        'total_restante_a_pagar': total_restante_a_pagar,
        'total_cartao': total_cartao_mes,
        'itens_fatura_detalhe': itens_fatura_detalhe, 
        'fatura_paga': fatura_paga,
        'total_investido': Caixinha.objects.aggregate(Sum('saldo_atual'))['saldo_atual__sum'] or 0,
        'categorias': Categoria.objects.all(),
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

def editar_caixinha(request, id):
    """Permite alterar as configurações e metas de uma caixinha"""
    caixinha = get_object_or_404(Caixinha, id=id)
    # instance=caixinha traz os dados antigos preenchidos no formulário genérico
    form = CaixinhaForm(request.POST or None, instance=caixinha)
    
    if form.is_valid():
        form.save()
        return redirect('caixinhas')
        
    return render(request, 'form_generico.html', {
        'form': form,
        'titulo': f'✏️ Editar Caixinha: {caixinha.nome}'
    })

def apagar_caixinha(request, id):
    """Exclui permanentemente a caixinha virtual"""
    caixinha = get_object_or_404(Caixinha, id=id)
    caixinha.delete()
    return redirect('caixinhas')

def detalhes_caixinha(request, id):
    caixinha = get_object_or_404(Caixinha, id=id)
    
    # 1. Busca todos os aportes/histórico vinculados a essa caixinha
    historico = Transacao.objects.filter(caixinha_destino=caixinha).order_by('-data_compra')
    
    # 2. Lógica da Meta
    falta_para_meta = 0
    porcentagem_meta = 0
    if caixinha.meta_valor:
        falta_para_meta = max(0, caixinha.meta_valor - caixinha.saldo_atual)
        porcentagem_meta = min(100, int((caixinha.saldo_atual / caixinha.meta_valor) * 100))

    # 3. Projeção de Rendimentos Futuros (Juros Compostos baseados no CDI)
    # Taxa CDI Mensal aproximada (0.85%) ajustada pelo % da caixinha
    taxa_mensal = Decimal(0.0085) * (caixinha.meta_cdi / 100)
    
    projecoes = []
    meses_alvo = [1, 3, 6, 12]
    for m in meses_alvo:
        saldo_projetado = caixinha.saldo_atual * ((1 + taxa_mensal) ** m)
        lucro_estimado = saldo_projetado - caixinha.saldo_atual
        projecoes.append({
            'meses': m,
            'total': saldo_projetado,
            'lucro': lucro_estimado
        })

    # 4. Dados para o Gráfico de Crescimento Mês a Mês (Simulação histórica/futura)
    # Vamos gerar uma linha mostrando a tendência de crescimento nos próximos 6 meses
    labels_grafico = []
    dados_grafico = []
    hoje = timezone.now().date()
    
    for i in range(7):
        data_futura = hoje + relativedelta(months=i)
        labels_grafico.append(data_futura.strftime("%b/%y"))
        dados_grafico.append(float(caixinha.saldo_atual * ((1 + taxa_mensal) ** i)))

    context = {
        'caixinha': caixinha,
        'historico': historico,
        'falta_para_meta': falta_para_meta,
        'porcentagem_meta': porcentagem_meta,
        'projecoes': projecoes,
        'labels_grafico': labels_grafico,
        'dados_grafico': dados_grafico,
    }
    return render(request, 'detalhes_caixinha.html', context)

def resgatar_caixinha(request):
    """Resgata valor parcial ou total de uma caixinha selecionada e gera a transação no extrato"""
    caixinhas = Caixinha.objects.all()
    categorias = Categoria.objects.all()

    if request.method == 'POST':
        caixinha_id = request.POST.get('caixinha_id')
        zerar_tudo = request.POST.get('zerar_tudo') == 'true'
        categoria_id = request.POST.get('categoria')
        descricao_motivo = request.POST.get('descricao', '').strip() # Descrição do motivo do resgate

        caixinha = get_object_or_404(Caixinha, id=caixinha_id)
        categoria_obj = get_object_or_404(Categoria, id=categoria_id)

        if zerar_tudo:
            valor_resgate = caixinha.saldo_atual
        else:
            try:
                valor_resgate = Decimal(request.POST.get('valor', '0').replace(',', '.'))
            except ValueError:
                valor_resgate = Decimal('0.0')

        if valor_resgate <= 0 or valor_resgate > caixinha.saldo_atual:
            messages.error(request, f"Valor inválido ou maior que o saldo disponível na caixinha '{caixinha.nome}'!")
            return redirect('resgatar_caixinha')


        # 1. Deduz o saldo da caixinha escolhida
        caixinha.saldo_atual -= valor_resgate
        caixinha.save()

        # 2. Registra a despesa no Extrato com a identificação clara
        categoria_obj = Categoria.objects.filter(id=categoria_id).first() if categoria_id else None
        descricao_final = f"Resgate: {descricao_motivo}" if descricao_motivo else f"Resgate da caixinha {caixinha.nome}"

        Transacao.objects.create(
            descricao=descricao_final,
            valor_total=valor_resgate,
            categoria=categoria_obj,
            data_compra=timezone.now().date(),
            caixinha_destino=caixinha, # Vínculo direto com a caixinha
            eh_cartao=False, # Resgate sempre sai do saldo
            eh_pagamento_fatura=False
        )

        messages.success(request, f"Resgate de R$ {valor_resgate:.2f} realizado com sucesso da caixinha '{caixinha.nome}'!")
        return redirect('caixinhas')

    return render(request, 'form_resgatar_caixinha.html', {
        'caixinhas': caixinhas,
        'categorias': categorias
    })

def novo_emprestimo_proprio(request):
    # [NOVO] Pega o ID da caixinha da URL para pré-selecionar
    caixinha_id = request.GET.get('caixinha_id')
    dados_iniciais = {}
    if caixinha_id:
        dados_iniciais['caixinha_origem'] = caixinha_id

    form = EmprestimoProprioForm(request.POST or None, initial=dados_iniciais)

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
    if request.method == 'POST':
        form = TransacaoForm(request.POST)
        if form.is_valid():
            # Cria o objeto, mas não salva no banco ainda
            nova_transacao_obj = form.save(commit=False)
            
            try:
                # transaction.atomic() garante que as duas ações (salvar despesa e atualizar saldo) ocorram juntas
                with transaction.atomic():
                    # 1. Salva a transação no banco de dados
                    nova_transacao_obj.save()
                    
                    # 2. A MÁGICA DO APORTE: 
                    # Verifica se o usuário escolheu uma caixinha E se a categoria tem a lógica reversa (Aporte)
                    if nova_transacao_obj.caixinha_destino and nova_transacao_obj.categoria.logica_reversa:
                        caixinha = nova_transacao_obj.caixinha_destino
                        caixinha.saldo_atual += nova_transacao_obj.valor_total
                        caixinha.save()
                        
                return redirect('dashboard')
            except Exception as e:
                # Caso ocorra um erro, ele não quebra o sistema, apenas imprime no console
                print(f"Erro ao salvar transação: {e}")
    else:
        form = TransacaoForm()
        
    return render(request, 'form_generico.html', {'form': form, 'titulo': '💸 Nova Despesa'})

def nova_receita(request):
    """Cria receitas avulsas ou dá baixa automática em Receitas Fixas"""
    
    # Verifica se a URL enviou o ID de um salário/receita fixa
    fixa_id = request.GET.get('fixa_id')
    dados_iniciais = {}
    
    if fixa_id:
        try:
            fixa = ReceitaFixa.objects.get(id=fixa_id)
            # Preenche automaticamente com os dados do planejamento
            dados_iniciais = {
                'descricao': fixa.descricao,
                'valor': fixa.valor,
                'data': timezone.now().date() # Já coloca a data de hoje!
            }
        except ReceitaFixa.DoesNotExist:
            pass

    # Carrega o formulário já com os dados preenchidos (se houver)
    form = ReceitaForm(request.POST or None, initial=dados_iniciais)
    
    if form.is_valid():
        form.save()
        return redirect('dashboard')
        
    return render(request, 'form_generico.html', {'form': form, 'titulo': '💰 Registrar Entrada'})

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

def editar_cartao(request, id):
    cartao = get_object_or_404(CartaoCredito, id=id)
    
    # Usa o form_generico já preenchido com os dados do cartão
    form = CartaoForm(request.POST or None, instance=cartao)
    
    if form.is_valid():
        form.save()
        return redirect('gerenciar_cartoes')
        
    return render(request, 'form_generico.html', {
        'form': form, 
        'titulo': f'✏️ Editar Cartão: {cartao.nome}'
    })

def apagar_cartao(request, id):
    cartao = get_object_or_404(CartaoCredito, id=id)
    cartao.delete()
    return redirect('gerenciar_cartoes')

# --- 5. GERENCIAMENTO DE CATEGORIAS ---

def gerenciar_categorias(request):
    mes_url = request.GET.get('mes')
    ano_url = request.GET.get('ano')
    data_hoje = timezone.now().date()
    
    try:
        if mes_url and ano_url:
            mes_int = int(mes_url)
            ano_int = int(ano_url)
            
            # Ajuste inteligente caso passe de 12 ou caia abaixo de 1
            if mes_int > 12:
                mes_int = 1
                ano_int += 1
            elif mes_int < 1:
                mes_int = 12
                ano_int -= 1
                
            data_ref = date(ano_int, mes_int, 1)
        else:
            data_ref = date(data_hoje.year, data_hoje.month, 1)
            
    except (ValueError, TypeError):
        data_ref = date(data_hoje.year, data_hoje.month, 1)

    # Identifica o mês anterior e o próximo para gerar os links das setinhas
    mes_anterior = data_ref - relativedelta(months=1)
    proximo_mes = data_ref + relativedelta(months=1)

    # --- RESUMO DO PLANEJAMENTO ---
    renda_fixa_total = ReceitaFixa.objects.aggregate(Sum('valor'))['valor__sum'] or 0
    categorias = Categoria.objects.all()
    total_planejado = categorias.aggregate(Sum('teto_mensal'))['teto_mensal__sum'] or 0
    sobra_prevista = renda_fixa_total - total_planejado

    # --- DETALHAMENTO POR CATEGORIA (MUDOU: FILTRA PELO MÊS SELECIONADO) ---
    categorias_com_detalhes = []
    for cat in categorias:
        # Soma o que já foi gasto nesta categoria no mês/ano selecionados
        gasto_debito = Transacao.objects.filter(
            categoria=cat, 
            eh_cartao=False, 
            data_compra__month=data_ref.month, 
            data_compra__year=data_ref.year
        ).aggregate(Sum('valor_total'))['valor_total__sum'] or 0
        
        gasto_cartao = Parcela.objects.filter(
            transacao__categoria=cat, 
            data_vencimento__month=data_ref.month, 
            data_vencimento__year=data_ref.year
        ).aggregate(Sum('valor'))['valor__sum'] or 0

        fixos_cartao = GastoFixo.objects.filter(
            categoria=cat, 
            eh_cartao=True
        ).aggregate(Sum('valor_previsto'))['valor_previsto__sum'] or 0
        
        # O Gasto Total soma os 3 (Débito + Parcelas do Cartão + Assinaturas do Cartão) no mês selecionado
        gasto_total = gasto_debito + gasto_cartao + fixos_cartao
        
        sobra = cat.teto_mensal - gasto_total

        categorias_com_detalhes.append({
            'id': cat.id,
            'nome': cat.nome,
            'teto_mensal': cat.teto_mensal,
            'gasto_total': gasto_total,
            'sobra': sobra if sobra > 0 else 0,
            'logica_reversa': cat.logica_reversa
        })

    # Puxa as caixinhas para o Modal de guardar dinheiro
    caixinhas = Caixinha.objects.all()

    # --- CONTEXTO COM AS VARIÁVEIS DE DATA PARA O HTML ---
    context = {
        'categorias': categorias_com_detalhes,
        'renda_fixa_total': renda_fixa_total,
        'total_planejado': total_planejado,
        'sobra_prevista': sobra_prevista,
        'caixinhas': caixinhas,
        
        # Variáveis novas do sistema de datas
        'data_ref': data_ref,
        'mes_ant_url': f"?mes={mes_anterior.month}&ano={mes_anterior.year}",
        'prox_mes_url': f"?mes={proximo_mes.month}&ano={proximo_mes.year}",
    }
    return render(request, 'lista_categorias.html', context)

def apagar_categoria(request, id):
    """Permite excluir uma categoria do sistema"""
    categoria = get_object_or_404(Categoria, id=id)

    categoria.delete()
    
    return redirect('gerenciar_categorias')

def guardar_sobra(request):
    """Função que tira o dinheiro do saldo livre e joga na caixinha"""
    if request.method == 'POST':
        categoria_id = request.POST.get('categoria_id')
        caixinha_id = request.POST.get('caixinha_id')
        valor = Decimal(request.POST.get('valor').replace(',', '.'))
        
        categoria = get_object_or_404(Categoria, id=categoria_id)
        caixinha = get_object_or_404(Caixinha, id=caixinha_id)
        
        # 1. Cria uma despesa para "tirar" o dinheiro do saldo do mês
        Transacao.objects.create(
            descricao=f"Sobra Guardada: {categoria.nome}",
            valor_total=valor,
            data_compra=timezone.now().date(),
            categoria=categoria, # Vincula a categoria para "zerar" a sobra na tabela
            eh_cartao=False
        )
        
        # 2. Adiciona o dinheiro na Caixinha escolhida
        caixinha.saldo_atual += valor
        caixinha.save()
        
    return redirect('gerenciar_categorias')

def nova_categoria(request):
    form = CategoriaForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect('gerenciar_categorias')
    return render(request, 'form_generico.html', {'form': form, 'titulo': '📂 Nova Categoria'})

def editar_categoria(request, id):
    categoria = get_object_or_404(Categoria, id=id)
    # O "instance=categoria" carrega os dados atuais no formulário
    form = CategoriaForm(request.POST or None, instance=categoria)
    
    if form.is_valid():
        form.save()
        return redirect('gerenciar_categorias')
        
    return render(request, 'form_generico.html', {
        'form': form, 
        'titulo': f'✏️ Editar Categoria: {categoria.nome}'
    })

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

def editar_receita(request, id):
    # Busca a receita pelo ID
    receita = get_object_or_404(Receita, id=id)
    
    if request.method == 'POST':
        # Atualiza os dados vindos do Modal
        receita.descricao = request.POST.get('descricao')
        receita.valor = request.POST.get('valor')
        
        # Converte a data texto para objeto data
        nova_data = request.POST.get('data')
        receita.data = datetime.strptime(nova_data, '%Y-%m-%d').date()
        
        receita.save()
        
        # Redireciona para o mês da receita (para você ver a alteração)
        return redirect(f'/?mes={receita.data.month}&ano={receita.data.year}')
    
    # Se tentar acessar direto pelo navegador sem ser POST, volta pra home
    return redirect('/')

def apagar_receita_fixa(request, id):
    item = get_object_or_404(ReceitaFixa, id=id)
    item.delete()
    return redirect('gerenciar_receitas_fixas')

def pagar_gasto_fixo(request, id_fixo):
    gasto_fixo = get_object_or_404(GastoFixo, id=id_fixo)
    mes = request.GET.get('mes', timezone.now().month)
    ano = request.GET.get('ano', timezone.now().year)
    
    if request.method == 'POST':
        valor_real = Decimal(request.POST.get('valor_real').replace(',', '.'))
        data_pagamento = request.POST.get('data_pagamento')
        
        usar_cartao = gasto_fixo.eh_cartao
        cartao_escolhido = gasto_fixo.cartao if usar_cartao else None
        
        # Pega a caixinha correta definida diretamente no cadastro do Gasto Recorrente!
        caixinha_vinculada = gasto_fixo.caixinha_destino

        with transaction.atomic():
            # 1. Cria a transação apontando para a caixinha certa
            Transacao.objects.create(
                descricao=f"Pgto: {gasto_fixo.nome}",
                valor_total=valor_real,
                data_compra=data_pagamento,
                gasto_fixo=gasto_fixo,
                categoria=gasto_fixo.categoria,
                eh_cartao=usar_cartao,
                cartao=cartao_escolhido,
                qtd_parcelas=1,
                caixinha_destino=caixinha_vinculada
            )
            
            # 2. Atualiza o saldo apenas se o gasto tiver uma caixinha vinculada
            if caixinha_vinculada:
                caixinha_vinculada.saldo_atual += valor_real
                caixinha_vinculada.save()
        
        return redirect(f'/?mes={mes}&ano={ano}')

    return render(request, 'pagar_fixo.html', {
        'fixo': gasto_fixo, 
        'mes': mes, 
        'ano': ano,
        'valor_sugerido': gasto_fixo.valor_previsto
    })

def extrato(request):
    """Lista todas as movimentações (Entradas e Saídas)"""
    
    # 1. Busca as Receitas (Entradas)
    receitas = Receita.objects.all().order_by('-data')
    
    # 2. Busca as Despesas (Saídas)
    despesas = Transacao.objects.all().order_by('-data_compra')
    
    # 3. Junta as duas listas manualmente
    movimentacoes = []
    
    for r in receitas:
        movimentacoes.append({
            'data': r.data,
            'descricao': r.descricao,
            'valor': r.valor,
            'tipo': 'entrada', # Marcador para saber que é dinheito entrando
            'id': r.id,
            'model': 'receita' # Para saber qual apagar se precisar
        })
        
    for d in despesas:
        movimentacoes.append({
            'data': d.data_compra,
            'descricao': d.descricao,
            'valor': d.valor_total,
            'tipo': 'saida', # Marcador para saber que é dinheiro saindo
            'eh_cartao': d.eh_cartao,
            'id': d.id,
            'model': 'transacao'
        })
    
    # 4. Ordena a lista final pela Data (do mais recente para o mais antigo)
    movimentacoes.sort(key=lambda x: x['data'], reverse=True)

    return render(request, 'extrato.html', {'transacoes': movimentacoes})

def editar_transacao(request, id):
    transacao = get_object_or_404(Transacao, id=id)
    
    if request.method == 'POST':
        form = TransacaoForm(request.POST, instance=transacao)
        if form.is_valid():
            transacao_salva = form.save()
            
            # Se for uma compra no cartão, recria as parcelas usando a regra do cartão
            if transacao_salva.eh_cartao and transacao_salva.cartao:
                # 1. Apaga as parcelas antigas vinculadas a esta transação
                Parcela.objects.filter(transacao=transacao_salva).delete()
                
                # 2. Calcula o novo valor de cada parcela
                valor_parcela = transacao_salva.valor_total / transacao_salva.qtd_parcelas
                
                # 3. Cria as novas parcelas respeitando o fechamento da fatura
                data_base = transacao_salva.data_compra
                for i in range(transacao_salva.qtd_parcelas):
                    data_parcela_atual = data_base + relativedelta(months=i)
                    # === CORREÇÃO AQUI: Usa a regra real do vencimento do cartão ===
                    data_vencimento_real = transacao_salva.cartao.get_data_vencimento_real(data_parcela_atual)
                    
                    Parcela.objects.create(
                        transacao=transacao_salva,
                        numero_parcela=i + 1,
                        valor=valor_parcela,
                        data_vencimento=data_vencimento_real
                    )
            
            return redirect('extrato')
    else:
        form = TransacaoForm(instance=transacao)
        
    return render(request, 'form_generico.html', {
        'form': form, 
        'titulo': f'✏️ Editar Transação: {transacao.descricao}'
    })

def apagar_transacao(request, id):
    """Permite excluir um lançamento errado"""
    transacao = get_object_or_404(Transacao, id=id)
    transacao.delete()
    return redirect(request.META.get('HTTP_REFERER', '/'))

def relatorio_categorias(request):
    """Gera a Super Tela Única de Análise Estratégica com múltiplos gráficos e Semáforo de 3 Meses"""
    mes_url = request.GET.get('mes')
    ano_url = request.GET.get('ano')
    data_hoje = timezone.now().date()
    
    try:
        if mes_url and ano_url:
            mes = int(mes_url)
            ano = int(ano_url)
            if mes > 12:
                mes = 1
                ano += 1
            elif mes < 1:
                mes = 12
                ano -= 1
            data_ref = date(ano, mes, 1)
        else:
            mes = data_hoje.month
            ano = data_hoje.year
            data_ref = date(ano, mes, 1)
    except (ValueError, TypeError):
        mes = data_hoje.month
        ano = data_hoje.year
        data_ref = date(ano, mes, 1)

    mes_anterior_url = data_ref - relativedelta(months=1)
    proximo_mes_url = data_ref + relativedelta(months=1)

    palavras_chave_aportes = ['aporte', 'investimento', 'poupança', 'caixinha', 'reserva']

    # ==========================================
    # 1. FUNÇÃO INTERNA PARA CALCULAR UM MÊS ISOLADO
    # ==========================================
    def calcular_dados_mes(m, a):
        # Verifica se o mês possui alguma movimentação real (Débito ou Cartão)
        tem_movimentacao_real = Transacao.objects.filter(
            data_compra__month=m, data_compra__year=a
        ).exists() or Parcela.objects.filter(
            data_vencimento__month=m, data_vencimento__year=a
        ).exists()

        avulsos = Transacao.objects.filter(
            eh_cartao=False, eh_pagamento_fatura=False, data_compra__month=m, data_compra__year=a
        ).aggregate(t=Sum('valor_total'))['t'] or 0.0
        
        parc = Parcela.objects.filter(
            data_vencimento__month=m, data_vencimento__year=a
        ).aggregate(t=Sum('valor'))['t'] or 0.0
        
        # SÓ SOMA OS GASTOS FIXOS SE O MÊS TIVER MOVIMENTAÇÃO REAL!
        # Isso impede que assinaturas vazem para meses passados onde o app não era usado.
        if tem_movimentacao_real:
            fixos = GastoFixo.objects.filter(eh_cartao=True).aggregate(t=Sum('valor_previsto'))['t'] or 0.0
        else:
            fixos = 0.0
        
        total_geral = float(avulsos) + float(parc) + float(fixos)
        
        # Filtro de Aportes do mês específico
        aportes = 0.0
        if tem_movimentacao_real:
            avulsos_ap = Transacao.objects.filter(
                eh_cartao=False, eh_pagamento_fatura=False, data_compra__month=m, data_compra__year=a
            ).select_related('categoria')
            
            parc_ap = Parcela.objects.filter(
                data_vencimento__month=m, data_vencimento__year=a
            ).select_related('transacao__categoria')
            
            fixos_ap = GastoFixo.objects.filter(eh_cartao=True).select_related('categoria')
            
            for g in avulsos_ap:
                nome_c = g.categoria.nome if g.categoria else 'Sem Categoria'
                if any(p in nome_c.lower() for p in palavras_chave_aportes):
                    aportes += float(g.valor_total or 0)
                    
            for p in parc_ap:
                nome_c = p.transacao.categoria.nome if p.transacao.categoria else 'Sem Categoria'
                if any(p_c in nome_c.lower() for p_c in palavras_chave_aportes):
                    aportes += float(p.valor or 0)
                    
            for f in fixos_ap:
                nome_c = f.categoria.nome if f.categoria else 'Sem Categoria'
                if any(p_c in nome_c.lower() for p_c in palavras_chave_aportes):
                    aportes += float(f.valor_previsto or 0)
                    
        custo_real = total_geral - aportes
        return total_geral, aportes, custo_real

    # ==========================================
    # 2. DADOS DO MÊS SELECIONADO (PIZZA E APORTES)
    # ==========================================
    gastos_avulsos = Transacao.objects.filter(
        eh_cartao=False, eh_pagamento_fatura=False, data_compra__month=mes, data_compra__year=ano
    ).values('categoria__id', 'categoria__nome').annotate(total=Sum('valor_total'))

    parcelas = Parcela.objects.filter(
        data_vencimento__month=mes, data_vencimento__year=ano
    ).select_related('transacao__categoria')

    fixos_cartao = GastoFixo.objects.filter(eh_cartao=True).select_related('categoria')

    dados_finais = {}

    for g in gastos_avulsos:
        nome = g['categoria__nome'] or 'Sem Categoria'
        cat_id = g['categoria__id'] or None
        if nome not in dados_finais: dados_finais[nome] = [0.0, cat_id]
        dados_finais[nome][0] += float(g['total'] or 0)

    for p in parcelas:
        nome = p.transacao.categoria.nome if p.transacao.categoria else 'Sem Categoria'
        cat_id = p.transacao.categoria.id if p.transacao.categoria else None
        if nome not in dados_finais: dados_finais[nome] = [0.0, cat_id]
        dados_finais[nome][0] += float(p.valor or 0)

    for f in fixos_cartao:
        nome = f.categoria.nome if f.categoria else 'Sem Categoria'
        cat_id = f.categoria.id if f.categoria else None
        if nome not in dados_finais: dados_finais[nome] = [0.0, cat_id]
        dados_finais[nome][0] += float(f.valor_previsto or 0)

    # Separa despesas puras de investimentos para os dois gráficos de pizza
    total_geral_saidas, total_aportes_mes, custo_mensal_real_atual = calcular_dados_mes(mes, ano)

    # Ordena o dicionário pelo valor de forma decrescente para a listagem lateral ficar bonita
    dados_ordenados = sorted(dados_finais.items(), key=lambda item: item[1][0], reverse=True)

    labels_despesas = []
    valores_despesas = []
    ids_despesas = []
    
    labels_aportes = []
    valores_aportes = []

    for nome, dados in dados_ordenados:
        if any(p in nome.lower() for p in palavras_chave_aportes):
            labels_aportes.append(nome)
            valores_aportes.append(dados[0])
        else:
            labels_despesas.append(nome)
            valores_despesas.append(dados[0])
            ids_despesas.append(dados[1])

    # ==========================================
    # 3. HISTÓRICO E CALCULO INTELIGENTE DA MÉDIA
    # ==========================================
    labels_historico = []
    entradas_historico = []
    saidas_historico = []
    
    meses_com_gastos_reais = 0
    soma_custos_reais_historico = 0.0

    for i in range(5, -1, -1):
        data_mes = data_ref - relativedelta(months=i)
        labels_historico.append(data_mes.strftime('%b/%y'))
        
        _, _, custo_real_m = calcular_dados_mes(data_mes.month, data_mes.year)
        
        # Só computa para o divisor da média se houver custo real de vida ativo no mês
        if custo_real_m > 0:
            meses_com_gastos_reais += 1
            soma_custos_reais_historico += custo_real_m

        total_entradas = Receita.objects.filter(
            data__month=data_mes.month, data__year=data_mes.year
        ).aggregate(total=Sum('valor'))['total'] or 0.0
        entradas_historico.append(float(total_entradas))
        saidas_historico.append(custo_real_m)

    # Média dinâmica baseada apenas nos meses com atividade de fato
    divisor_media = meses_com_gastos_reais if meses_com_gastos_reais > 0 else 1
    media_custo_vida = soma_custos_reais_historico / divisor_media
    
    if media_custo_vida == 0:
        media_custo_vida = custo_mensal_real_atual

    # Metas calibradas (3 meses mínimo, 6 meses ideal)
    reserva_minima = media_custo_vida * 3
    reserva_ideal = media_custo_vida * 6

    # === CORREÇÃO AQUI: Busca apenas a caixinha específica da Reserva ===
    # O filtro 'nome__icontains' garante que vai achar mesmo se estiver com letras maiúsculas/minúsculas
    caixinha_emergencia = Caixinha.objects.filter(nome__icontains='Reserva de Emergência').first()
    
    # Se a caixinha existir, pega o saldo dela. Se não existir ou estiver zerada, assume 0.0
    saldo_real_reserva = float(caixinha_emergencia.saldo_atual) if caixinha_emergencia else 0.0
    
    # O progresso agora calcula com base no dinheiro real da segurança
    progresso_reserva = min(int((saldo_real_reserva / reserva_ideal) * 100), 100) if reserva_ideal > 0 else 0

    # ==========================================
    # 4. MONTAGEM DO SEMÁFORO DE 3 MESES
    # ==========================================
    meses_semaforo = [
        data_ref - relativedelta(months=1),  # Anterior
        data_ref,                            # Atual
        data_ref + relativedelta(months=1)   # Próximo
    ]
    
    semaforo_dados = []
    
    # Busca o total de receitas fixas cadastradas no seu sistema para usar como previsão
    # (Ajuste o nome do Model se no seu projeto for ReceitaFixa no singular)
    from finance.models import ReceitaFixa 
    total_receitas_fixas_recorrentes = float(ReceitaFixa.objects.aggregate(t=Sum('valor'))['t'] or 0.0)

    for d_m in meses_semaforo:
        t_g, t_ap, c_re = calcular_dados_mes(d_m.month, d_m.year)
        
        # Busca o que já foi depositado de fato no mês
        total_lancado = Receita.objects.filter(data__month=d_m.month, data__year=d_m.year).aggregate(t=Sum('valor'))['t'] or 0.0
        t_ent = float(total_lancado)
        
        # === A MÁGICA AQUI: Se for um mês futuro e estiver zerado, assume a receita fixa esperada ===
        if t_ent == 0.0 and (d_m.year > data_hoje.year or (d_m.year == data_hoje.year and d_m.month > data_hoje.month)):
            t_ent = total_receitas_fixas_recorrentes
        
        sobra_real = t_ent - t_g
        
        if sobra_real < 0:
            status = "Déficit ⚠️"
            cor = "text-danger fw-bold"
        elif t_g == 0 and t_ent == 0:
            status = "Sem lançamentos"
            cor = "text-muted"
        else:
            status = "Saudável 🎯"
            cor = "text-success fw-bold"
            
        semaforo_dados.append({
            'label': d_m.strftime('%B / %Y'),
            'mes': d_m.month,
            'ano': d_m.year,
            'entradas': t_ent,
            'custo_real': c_re,
            'aportes': t_ap,
            'sobra': sobra_real,
            'status': status,
            'cor': cor
        })

    context = {
        'mes': mes, 'ano': ano, 'data_ref': data_ref,
        'mes_ant_url': f"?mes={mes_anterior_url.month}&ano={mes_anterior_url.year}" if 'mes_anterior_url' in locals() else f"?mes={(data_ref - relativedelta(months=1)).month}&ano={(data_ref - relativedelta(months=1)).year}",
        'prox_mes_url': f"?mes={(data_ref + relativedelta(months=1)).month}&ano={(data_ref + relativedelta(months=1)).year}",
        'labels': labels_despesas,
        'data': valores_despesas,
        'ids_categorias': ids_despesas,
        'labels_aportes': labels_aportes,
        'valores_aportes': valores_aportes,
        'custo_mensal_real': custo_mensal_real_atual,
        'total_aportes': total_aportes_mes,
        'total_geral': total_geral_saidas,
        'labels_historico': labels_historico,
        'entradas_historico': entradas_historico,
        'saidas_historico': saidas_historico,
        'media_custo_vida': media_custo_vida,
        'reserva_minima': reserva_minima,
        'reserva_ideal': reserva_ideal,
        'saldo_caixinhas': saldo_real_reserva,
        'progresso_reserva': progresso_reserva,
        'semaforo_dados': semaforo_dados
    }
    return render(request, 'relatorio_categorias.html', context)

def relatorio_anual(request):
    """Gera o Semáforo projetando como o mês DEVE TERMINAR"""
    ano = int(request.GET.get('ano', timezone.now().year))
    hoje = timezone.now().date()
    mes_atual = hoje.month
    ano_atual = hoje.year
    
    grid_meses = []
    
    # Valores de planejamento geral
    receita_fixa_total = ReceitaFixa.objects.aggregate(Sum('valor'))['valor__sum'] or 0
    gasto_fixo_total = GastoFixo.objects.aggregate(Sum('valor_previsto'))['valor_previsto__sum'] or 0

    # 1. Pega o saldo real do último dia do ano anterior (Base de cálculo)
    r_hist = Receita.objects.filter(data__lt=date(ano, 1, 1)).aggregate(Sum('valor'))['valor__sum'] or 0
    d_hist = Transacao.objects.filter(eh_cartao=False, data_compra__lt=date(ano, 1, 1)).aggregate(Sum('valor_total'))['valor_total__sum'] or 0
    saldo_acumulado = r_hist - d_hist

    for i in range(1, 13):
        data_ref = date(ano, i, 1)
        
        # O mês é passado? (ex: estamos em maio e o loop está em março)
        is_past = ano < ano_atual or (ano == ano_atual and i < mes_atual)
        
        if is_past:
            # MESES PASSADOS: Saldo real exato cravado no último dia do mês
            data_limite = data_ref + relativedelta(months=1)
            r_total = Receita.objects.filter(data__lt=data_limite).aggregate(Sum('valor'))['valor__sum'] or 0
            d_total = Transacao.objects.filter(eh_cartao=False, data_compra__lt=data_limite).aggregate(Sum('valor_total'))['valor_total__sum'] or 0
            
            saldo = r_total - d_total
            saldo_acumulado = saldo # Atualiza a bola de neve real
            
        else:
            # MÊS ATUAL E FUTUROS: Projeção de como o mês VAI FECHAR (O que você queria!)
            
            # A. Receitas Projetadas (Se já entrou um dinheiro extra, ele usa o maior valor)
            receitas_reais = Receita.objects.filter(data__month=i, data__year=ano).aggregate(Sum('valor'))['valor__sum'] or 0
            receita_projetada = max(receita_fixa_total, receitas_reais)
            
            # B. Despesas Projetadas (Soma os compromissos fixos, cartão e avulsas)
            parcelas = Parcela.objects.filter(data_vencimento__month=i, data_vencimento__year=ano).aggregate(Sum('valor'))['valor__sum'] or 0
            avulsas = ContaAvulsa.objects.filter(data_vencimento__month=i, data_vencimento__year=ano).aggregate(Sum('valor'))['valor__sum'] or 0
            
            # Pega também os gastos que você já fez no débito (ex: padaria) para não ignorar o que já foi gasto hoje
            gastos_extras_debito = Transacao.objects.filter(
                eh_cartao=False, 
                eh_pagamento_fatura=False,
                gasto_fixo__isnull=True,    # Ignora fixos (para não cobrar 2x)
                conta_avulsa__isnull=True,  # Ignora avulsas (para não cobrar 2x)
                data_compra__month=i, 
                data_compra__year=ano
            ).aggregate(Sum('valor_total'))['valor_total__sum'] or 0
            
            despesa_projetada = gasto_fixo_total + parcelas + avulsas + gastos_extras_debito
            
            # C. Matemática do Fechamento
            saldo = saldo_acumulado + receita_projetada - despesa_projetada
            saldo_acumulado = saldo # Atualiza a bola de neve projetada para o próximo mês

        grid_meses.append({
            'mes_num': i,
            'mes_nome': data_ref.strftime('%B'),
            'saldo': saldo,
            'cor': 'success' if saldo >= 0 else 'danger',
            'passado': is_past
        })

    return render(request, 'relatorio_anual.html', {'ano': ano, 'grid': grid_meses})

def detalhes_gastos_categoria(request, categoria_id):
    """Exibe a listagem completa e exclusiva de gastos de uma categoria ordenados do mais caro para o mais barato"""
    categoria = get_object_or_404(Categoria, id=categoria_id)
    mes = int(request.GET.get('mes', timezone.now().month))
    ano = int(request.GET.get('ano', timezone.now().year))
    
    detalhes_gastos = []
    
    # 1. Débito / Dinheiro
    transacoes_debito = Transacao.objects.filter(
        categoria=categoria,
        eh_cartao=False,
        eh_pagamento_fatura=False,
        data_compra__month=mes,
        data_compra__year=ano
    )
    for t in transacoes_debito:
        detalhes_gastos.append({
            'data': t.data_compra,
            'descricao': t.descricao,
            'valor': float(t.valor_total),
            'tipo': 'Débito / PIX'
        })
        
    # 2. Parcelas de Cartão
    parcelas_cartao = Parcela.objects.filter(
        transacao__categoria=categoria,
        data_vencimento__month=mes,
        data_vencimento__year=ano
    ).select_related('transacao')
    for p in parcelas_cartao:
        detalhes_gastos.append({
            'data': p.data_vencimento,
            'descricao': f"{p.transacao.descricao} ({p.numero_parcela}/{p.transacao.qtd_parcelas})",
            'valor': float(p.valor),
            'tipo': 'Cartão de Crédito'
        })
        
    # 3. Gastos Fixos / Assinaturas no Cartão
    # CORREÇÃO: Filtra os gastos fixos para garantir que eles sejam do mês/ano da consulta.
    # Isso evita que assinaturas de outros meses apareçam no detalhamento.
    fixos_cartao = GastoFixo.objects.filter(
        categoria=categoria, eh_cartao=True, dia_vencimento__gt=0 # Apenas para simular a data
    )
    for f in fixos_cartao:
        detalhes_gastos.append({
            # CORREÇÃO: Garante que a data do gasto recorrente respeite o mês/ano da consulta.
            # A função min() evita erros em meses com menos de 31 dias.
            # O relativedelta(day=f.dia_vencimento) ajusta para o dia correto.
            'data': date(ano, mes, 1) + relativedelta(day=min(int(f.dia_vencimento), 28)),
            'descricao': f"{f.nome} (Assinatura)",
            'valor': float(f.valor_previsto),
            'tipo': 'Cartão (Recorrente)'
        })
        
    # Ordenação do mais caro para o mais barato
    detalhes_gastos.sort(key=lambda x: x['valor'], reverse=True)
    total_gasto = sum(item['valor'] for item in detalhes_gastos)
    
    context = {
        'categoria': categoria,
        'gastos': detalhes_gastos,
        'total': total_gasto,
        'mes': mes,
        'ano': ano,
    }
    return render(request, 'detalhes_gastos_categoria.html', context)

def pagar_fatura_mensal(request):
    # Pega o mês/ano da URL ou usa o atual
    mes = int(request.GET.get('mes', timezone.now().month))
    ano = int(request.GET.get('ano', timezone.now().year))
    
    # 1. Calcula o Valor Exato
    soma_parcelas = Parcela.objects.filter(
        data_vencimento__month=mes,
        data_vencimento__year=ano
    ).aggregate(Sum('valor'))['valor__sum'] or 0
    
    soma_assinaturas = 0
    fixos_cartao = GastoFixo.objects.filter(eh_cartao=True)
    for fixo in fixos_cartao:
        ja_lancado = Transacao.objects.filter(gasto_fixo=fixo, data_compra__month=mes, data_compra__year=ano).exists()
        if not ja_lancado:
            soma_assinaturas += fixo.valor_previsto
            
    total_fatura = soma_parcelas + soma_assinaturas
    
    # 2. Cria o Pagamento (se tiver valor)
    if total_fatura > 0:
        descricao_padrao = f"Pgto Fatura Cartão ({mes}/{ano})"
        
        # Verifica se já não existe para não duplicar
        ja_pago = Transacao.objects.filter(descricao=descricao_padrao).exists()
        
        if not ja_pago:
            Transacao.objects.create(
                descricao=descricao_padrao,
                valor_total=total_fatura,
                data_compra=timezone.now().date(), # Sai do saldo HOJE
                eh_cartao=False, # Sai da Conta Corrente (Débito)
                eh_pagamento_fatura=True # MARCA COMO FATURA PAGA
            )
    
    # 3. O PULO DO GATO: Redireciona para o mês que você estava olhando!
    # Se você pagou Fevereiro, volta para Fevereiro.
    return redirect(f'/?mes={mes}&ano={ano}')

def adicionar_conta_avulsa(request):
    if request.method == 'POST':
        titulo = request.POST.get('titulo')
        # Troca a vírgula por ponto para evitar erros ao salvar
        valor = request.POST.get('valor').replace(',', '.')
        data_venc = request.POST.get('data_vencimento')
        categoria_id = request.POST.get('categoria_id')
        
        # Pega a quantidade de meses (se não vier nada, padrão é 1)
        qtd_meses = int(request.POST.get('qtd_meses', 1)) 
        
        # Busca o objeto categoria no banco
        categoria_obj = None
        if categoria_id:
            categoria_obj = Categoria.objects.get(id=categoria_id)

        data_obj = datetime.strptime(data_venc, '%Y-%m-%d').date()

        # O MÁGICO AQUI: Cria uma conta para cada mês
        for i in range(qtd_meses):
            # Avança o mês a cada repetição
            data_parcela = data_obj + relativedelta(months=i)
            
            # Adiciona o (1/3), (2/3) no nome se for parcelado
            titulo_parcela = titulo
            if qtd_meses > 1:
                titulo_parcela = f"{titulo} ({i+1}/{qtd_meses})"

            ContaAvulsa.objects.create(
                titulo=titulo_parcela,
                valor=valor,
                data_vencimento=data_parcela,
                categoria=categoria_obj
            )
            
        return redirect(f'/?mes={data_obj.month}&ano={data_obj.year}')
    
    return redirect('/')

def pagar_conta_avulsa(request, id):
    conta = ContaAvulsa.objects.get(id=id)
    
    # Cria a transação usando a categoria que foi definida na conta avulsa
    Transacao.objects.create(
        descricao=conta.titulo,
        valor_total=conta.valor,
        data_compra=timezone.now().date(),
        eh_cartao=False,
        conta_avulsa_id=id,
        categoria=conta.categoria # <--- O PULO DO GATO: Passa a categoria pra frente
    )
    
    mes = request.GET.get('mes')
    ano = request.GET.get('ano')
    return redirect(f'/?mes={mes}&ano={ano}')

def apagar_conta_avulsa(request, id):
    conta = ContaAvulsa.objects.get(id=id)
    
    # Salva a data para redirecionar para o mês certo
    mes = conta.data_vencimento.month
    ano = conta.data_vencimento.year
    
    conta.delete()
    
    return redirect(f'/?mes={mes}&ano={ano}')

def editar_conta_avulsa(request, id):
    conta = ContaAvulsa.objects.get(id=id)
    
    if request.method == 'POST':
        conta.titulo = request.POST.get('titulo')
        conta.valor = request.POST.get('valor')
        
        # Converte a data string para objeto date
        nova_data = request.POST.get('data_vencimento')
        conta.data_vencimento = datetime.strptime(nova_data, '%Y-%m-%d').date()
        
        cat_id = request.POST.get('categoria_id')
        if cat_id:
            conta.categoria_id = cat_id
            
        conta.save()
        
        # SE JÁ TIVER PAGO, ATUALIZA A TRANSAÇÃO TAMBÉM
        transacao = Transacao.objects.filter(conta_avulsa=conta).first()
        if transacao:
            transacao.descricao = conta.titulo
            transacao.valor_total = conta.valor
            transacao.categoria = conta.categoria
            # A data da compra mantemos a original do pagamento
            transacao.save()
            
        # Redireciona para o mês da NOVA data de vencimento
        return redirect(f'/?mes={conta.data_vencimento.month}&ano={conta.data_vencimento.year}')
    
    return redirect('/')

def editar_gasto_fixo(request, id):
    # Puxa o gasto fixo pelo ID
    fixo = get_object_or_404(GastoFixo, id=id)
    
    # Carrega o nosso formulário inteligente já preenchido com os dados (instance=fixo)
    form = GastoFixoForm(request.POST or None, instance=fixo)
    
    if form.is_valid():
        form.save()
        # Após salvar, volta para a lista de contas fixas
        return redirect('gerenciar_fixos')
        
    # Se não for POST (quando clica no botão ✏️), abre a tela do formulário!
    return render(request, 'form_generico.html', {
        'form': form, 
        'titulo': f'✏️ Editar Recorrente: {fixo.nome}'
    })

def excluir_gasto_fixo(request, id):
    fixo = GastoFixo.objects.get(id=id)
    fixo.delete()
    return redirect('/')

def excluir_receita(request, id):
    receita = Receita.objects.get(id=id)
    receita.delete()
    return redirect(request.META.get('HTTP_REFERER', '/'))
