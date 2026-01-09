# 💰 FinControl - Gestão Financeira Pessoal

Sistema de controle financeiro inteligente desenvolvido com Django. O foco do projeto é oferecer uma visão clara do saldo real (caixa) versus previsões futuras, com tratamento diferenciado para cartões de crédito e investimentos.

## 🚀 Funcionalidades Principais

- **Dashboard Inteligente:**
  - Visão temporal: Mês Passado (Histórico), Mês Atual (Execução) e Meses Futuros (Previsão).
  - Diferenciação entre "Saldo em Conta" e "Fatura de Cartão".
  
- **💳 Gestão de Cartão de Crédito:**
  - Lançamento de despesas com parcelamento automático.
  - Reconhecimento inteligente do dia de fechamento (jogando compras para o mês seguinte).
  - Pagamento de fatura: abate do saldo apenas no ato do pagamento.
  - Assinaturas recorrentes (ex: Netflix) somadas automaticamente na previsão da fatura.

- **🐖 Caixinhas & Investimentos:**
  - Sistema de "Caixinhas" para separar dinheiro do saldo corrente.
  - Projeção de rendimento baseada no CDI.
  - Funcionalidade de "Auto-Empréstimo" e aportes diretos do saldo.

- **📊 Relatórios:**
  - **Semáforo Anual:** Visão macro do ano (Verde/Vermelho) para identificar meses críticos.
  - **Gráficos por Categoria:** Análise de gastos (Pizza/Barras).
  - Extrato detalhado para auditoria de lançamentos.

## 🛠️ Tecnologias Utilizadas

- **Backend:** Python 3.12, Django 5.x
- **Banco de Dados:** SQLite (Padrão)
- **Frontend:** HTML5, CSS3 (Bootstrap 5), JavaScript (Chart.js)
- **Bibliotecas:** `python-dateutil` (cálculos de data), `django-bootstrap-v5`.

## ⚙️ Como rodar o projeto localmente

1. **Clone o repositório:**
   ```bash
   git clone [https://github.com/SEU_USUARIO/fin_control.git](https://github.com/SEU_USUARIO/fin_control.git)
   cd fin_control
   ```

2. **Crie e ative um ambiente virtual:**

    ```Bash
    python -m venv venv
    # No Windows:
    venv\Scripts\activate
    # No Mac/Linux:
    source venv/bin/activate
    ```

3. **Instale as dependências:**

    ```Bash
    pip install -r requirements.txt
    ```

4. **Prepare o Banco de Dados:**

    ```Bash
    python manage.py migrate
    ```

5. **Inicie o Servidor:**

    ```Bash
    python manage.py runserver
    ```

6. Acesse: Abra `http://127.0.0.1:8000/` no navegador.
