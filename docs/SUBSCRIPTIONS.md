# Assinaturas e cobrança

O Organizaê é vendido por mensalidade. Cada negócio tem **uma assinatura**, com um destes estados:

| Estado | Significa | Acesso |
|---|---|---|
| `TRIALING` | Teste grátis (`TRIAL_DAYS`, padrão 15) | Total até o fim do teste |
| `ACTIVE` | Pago | Total |
| `PAST_DUE` | Não pagou no vencimento; carência de `GRACE_DAYS` (padrão 5) | Total até o fim da carência |
| `SUSPENDED` | Teste ou carência acabou sem pagamento | **Somente leitura**: escritas respondem `402 SUBSCRIPTION_SUSPENDED` e a página pública deixa de aceitar reservas |
| `CANCELED` | Encerrada | Nenhum: tudo responde `402 SUBSCRIPTION_CANCELED` |

Os dados nunca são apagados por inadimplência. Pagar reativa na hora.

O prazo do teste e da carência é conferido a cada requisição, então o bloqueio **não depende de um job estar agendado**.

## Preço

`plans.price_cents`, em centavos. O plano padrão (`standard`) nasce com **4990** (R$ 49,90) pela migration. Mudar o preço de um plano não altera as assinaturas que já existem no gateway.

## Configuração (`.env`)

| Variável | Para quê |
|---|---|
| `TRIAL_DAYS`, `GRACE_DAYS` | Dias de teste e de carência |
| `ASAAS_API_KEY` | Chave do Asaas. Vazia: o checkout responde `503` |
| `ASAAS_BASE_URL` | Sandbox por padrão (`https://sandbox.asaas.com/api/v3`); produção é `https://api.asaas.com/v3` |
| `ASAAS_WEBHOOK_TOKEN` | Token longo e aleatório. Vazio: o webhook responde `503` (nunca aceita sem autenticar) |

## Rotas

**Do profissional** (nunca bloqueadas, para quem está suspenso poder pagar):

- `GET /api/v1/subscription`: estado, dias restantes e preço.
- `POST /api/v1/subscription/checkout`: cria o cliente e a assinatura no Asaas (uma vez só) e devolve `{ "payment_url" }`. Quem ainda está em teste só é cobrado no fim dele. Chamar de novo devolve o link de novo, sem duplicar nada.

**Webhook**: `POST /api/v1/webhooks/asaas`, autenticado pelo header `asaas-access-token`.

- `PAYMENT_CONFIRMED` / `PAYMENT_RECEIVED`: ativa e cobre um mês a partir do vencimento da cobrança.
- `PAYMENT_OVERDUE`: abre a carência. Aviso de uma cobrança que o período já cobre é ignorado (chegou fora de ordem).
- Cada evento é aplicado **uma vez** (`gateway_events`); reenvios respondem `200 {"result": "duplicate"}`.
- Outros eventos respondem `200` sem efeito.

**Da equipe** (só usuários com `is_platform_admin`, prefixo `/api/v1/admin`):

- `GET /businesses`, `GET /businesses/{id}`: lista (filtro `status`, busca `q`, paginação até 100) e detalhe.
- `POST /businesses/{id}/extend-trial` (`{days: 1..90}`), `/suspend`, `/reactivate` (`{days}` opcional, padrão 30, período de cortesia) e `/cancel` (também cancela a cobrança no Asaas).
- `GET /metrics`: contagem por estado e receita mensal recorrente (`ACTIVE` + `PAST_DUE`).

Para tornar alguém administrador (a pessoa precisa já ter se cadastrado):

```bash
uv run python -m scripts.create_platform_admin pessoa@exemplo.com
```

## Ligando o Asaas (pendente)

1. Criar a conta no Asaas e a chave do **sandbox**; preencher `ASAAS_API_KEY`.
2. Gerar um `ASAAS_WEBHOOK_TOKEN` aleatório e cadastrar o mesmo valor no Asaas, apontando o webhook para `https://<api>/api/v1/webhooks/asaas` com os eventos de cobrança.
3. Testar o ciclo no sandbox: checkout → pagar → confirmar que a assinatura virou `ACTIVE`.

### O que foi escrito sem poder testar contra o Asaas real

O cliente (`gateway.py`) foi feito de memória da API v3 e testado só com respostas simuladas. **Confira no sandbox antes de ir para produção:**

- a chave vai no header `access_token` (não é `Bearer`);
- se o Asaas exige `cpfCnpj` no cliente para criar a cobrança (hoje o cliente é criado só com nome, e-mail e `externalReference`);
- o campo `invoiceUrl` da primeira cobrança em `GET /subscriptions/{id}/payments`;
- o formato do corpo do webhook: `id` do evento, `event` e `payment.{subscription, dueDate}`.

## Job diário

```bash
uv run python -m scripts.process_subscriptions
```

Rode **uma vez por dia** num agendador do servidor (hoje nada o agenda). Ele:

- suspende teste que acabou sem pagamento;
- põe em carência quem está `ACTIVE` mas cujo período pago venceu sem renovar (pagamento que o gateway nunca confirmou, ou cortesia da equipe que acabou); a carência conta do fim do período, não da hora em que o job rodou;
- suspende carência esgotada.

É seguro rodar mais de uma vez e rodar duas ao mesmo tempo (linhas já travadas por outra execução são puladas). O acesso também é recusado pelo prazo sem o job: o job só organiza os estados.

## Pendente

- Avisos por e-mail (teste acabando, atraso, suspensão): dependem do envio de e-mail da US-015 (PR #42) estar mergeado.
- Pagamento com o profissional suspenso, mas sem gateway configurado: só a equipe consegue reativar (`/reactivate`).
