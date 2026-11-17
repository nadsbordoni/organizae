"""Approved nonnumeric explanations; facts and amounts never come from the model."""

from app.modules.financial_insights.schemas import InsightType

GUIDANCE_VERSION = "1"
GUIDANCE = {
    InsightType.REVENUE_DROP: {
        "explanations": {
            "cash_received": "As entradas de caixa diminuíram no intervalo comparado. Os registros não comprovam as causas.",
            "check_receipts": "Receita recebida considera os pagamentos registrados, sem somar valores ainda pendentes. A causa da redução precisa ser verificada.",
        },
        "actions": {
            "review_receivables": "Confira os recebimentos pendentes antes de estimar o caixa disponível.",
            "check_records": "Verifique se todos os recebimentos do período foram registrados corretamente.",
            "compare_activity": "Compare os registros de vendas e atendimentos dos dois períodos para investigar possíveis fatores.",
        },
    },
    InsightType.EXPENSE_INCREASE: {
        "explanations": {
            "cash_paid": "Os pagamentos de despesas aumentaram no intervalo comparado. Isso não comprova aumento dos preços ou dos custos contratados.",
            "payment_timing": "O alerta considera despesas efetivamente pagas. Consulte os lançamentos para verificar o que compõe a diferença.",
        },
        "actions": {
            "review_categories": "Consulte as despesas por categoria para identificar onde os pagamentos se concentraram.",
            "check_one_offs": "Verifique nos lançamentos se houve pagamentos pontuais ou diferenças nas datas de pagamento.",
            "review_contracts": "Revise os compromissos recorrentes antes de decidir sobre renegociações.",
        },
    },
    InsightType.NEGATIVE_RESULT: {
        "explanations": {
            "negative_cash": "As despesas pagas superaram as receitas recebidas. Esse resultado financeiro não equivale ao lucro contábil.",
            "liquidity": "O resultado realizado indica saída de caixa superior à entrada registrada no período. As causas não são determinadas por este alerta.",
        },
        "actions": {
            "review_cash_flow": "Revise o fluxo de caixa e os vencimentos antes de assumir novos compromissos.",
            "review_receivables": "Confira os recebimentos pendentes e suas datas previstas.",
            "review_payments": "Avalie quais pagamentos podem ser planejados ou negociados, sem alterar registros automaticamente.",
        },
    },
    InsightType.OVERDUE_EXPENSES: {
        "explanations": {
            "pending_due": "Há despesas pendentes com vencimento anterior à data de referência. O alerta não presume que pagamentos tenham ocorrido fora do sistema.",
            "reconcile": "A pendência reflete o status dos lançamentos registrados; confira os comprovantes antes de concluir que falta pagamento.",
        },
        "actions": {
            "check_proofs": "Confira os comprovantes para verificar se há pagamentos realizados ainda não registrados.",
            "review_due_dates": "Revise os vencimentos das despesas pendentes e organize os compromissos.",
            "contact_suppliers": "Quando a pendência for confirmada, avalie contato com os fornecedores para planejar a regularização.",
        },
    },
}


def default_guidance(kind: InsightType) -> tuple[str, list[str]]:
    options = GUIDANCE[kind]
    return next(iter(options["explanations"].values())), list(
        options["actions"].values()
    )[:2]
