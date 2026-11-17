# US-030 — Extração financeira de imagem/PDF

Backend para obter uma prévia a partir de um comprovante, recibo ou nota, usando o Gemini multimodal existente. Não cadastra lançamentos ou categorias e não altera o fluxo de confirmação do chat. Nenhum arquivo do frontend foi modificado nesta tarefa.

## Contrato

`POST /api/v1/financial/document-extraction`

Autenticação: `Authorization: Bearer <JWT>`, obtido no login existente. A empresa vem exclusivamente do usuário autenticado. A rota não aceita parâmetros de consulta, `business_id` no formulário ou mais de um arquivo.

Corpo `multipart/form-data` com somente o campo binário `file`. Aceita conteúdo JPEG (JPG/JPEG), PNG ou PDF até **5 MiB (5.242.880 bytes)**, alinhado ao limite do formulário. Extensão e Content-Type declarados não determinam o formato: as imagens são verificadas e decodificadas, e o PDF é analisado estruturalmente.

Limites adicionais: imagens de até 20 milhões de pixels; PDF de 1 a 20 páginas, sem criptografia. O corpo multipart também é limitado a 5 MiB + 64 KiB de cabeçalhos/delimitadores. Esses limites evitam processamento desproporcional de arquivos pequenos e complexos. Uploads podem usar o spool temporário do framework durante a requisição; os arquivos são fechados e descartados ao final. Não há armazenamento permanente ou envio pela API Files do Gemini: o conteúdo é enviado inline.

Resposta HTTP 200:

```json
{
  "document_type": "payment_receipt",
  "readability": "readable",
  "extracted_data": {
    "type": "EXPENSE",
    "description": "Compra de materiais",
    "amount": "150.00",
    "category_id": null,
    "competence_date": null,
    "payment_date": "2026-11-17",
    "due_date": null,
    "status": "PAID",
    "payment_method": "pix",
    "scheduled": false
  },
  "field_assessments": [
    {"field": "type", "source": "suggested", "evidence": "Empresa identificada como pagadora"},
    {"field": "description", "source": "suggested", "evidence": "Finalidade informada"},
    {"field": "amount", "source": "extracted", "evidence": "Valor total da transação"},
    {"field": "category_id", "source": "unknown", "evidence": null},
    {"field": "competence_date", "source": "unknown", "evidence": null},
    {"field": "payment_date", "source": "extracted", "evidence": "Data da liquidação"},
    {"field": "due_date", "source": "unknown", "evidence": null},
    {"field": "status", "source": "extracted", "evidence": "Transação concluída"},
    {"field": "payment_method", "source": "extracted", "evidence": "Modalidade Pix"},
    {"field": "scheduled", "source": "extracted", "evidence": "Transação concluída, não agendada"}
  ],
  "missing_fields": ["category_id", "competence_date", "due_date"],
  "warnings": [
    "Não foi possível identificar uma categoria com segurança.",
    "Há campos não identificados. Revise e complete antes de salvar."
  ],
  "requires_review": true
}
```

`amount` utiliza `Decimal`, com as mesmas restrições do cadastro financeiro (positivo, até 12 dígitos e duas casas decimais), serializado em texto. Não são usados cálculos com float. Datas são ISO `YYYY-MM-DD`, sem substituição pela data atual.

`document_type`: `receipt`, `invoice`, `payment_receipt`, `other` ou `unknown`. `readability`: `readable`, `partial` ou `unreadable`. Um documento válido mas ilegível retorna 200 com campos nulos e avisos. Informações contraditórias levam à remoção de todos os valores da prévia, para revisão manual.

Há uma avaliação por campo: `extracted` para dado explícito segundo o modelo, `suggested` para interpretação e `unknown` para ausente ou descartado. Categorias aceitas são sempre sugestões. Essas classificações são avaliações da IA, não garantias de exatidão ou pontuações calibradas. A revisão é sempre obrigatória. `missing_fields` lista todos os campos nulos, inclusive opcionais; nem todos são obrigatórios para salvar um lançamento.

## Mapeamento do formulário atual

Análise baseada em `apps/site/src/components/painel/EntryForm.astro` e `src/types/painel.ts`, sem modificá-los:

| Campo visual | Campo da extração | Observação para integração futura |
| --- | --- | --- |
| Receita / Despesa | `type` | Enums existentes `INCOME` / `EXPENSE`; pode ser nulo se não for possível determinar a direção em relação à empresa. |
| Descrição (`descricao`) | `description` | Até 500 caracteres. |
| Valor (`valor`) | `amount` | Texto decimal da API; apresentação em reais fica para o cliente. |
| Categoria (`categoria`) | `category_id` | Somente categoria existente da empresa, compatível com `type`. |
| Data de competência (`competencia`) | `competence_date` | Não confundir automaticamente com emissão, vencimento ou pagamento. |
| Data de pagamento (`pagamento`) | `payment_date` / `due_date` | A tela também usa essa entrada para o previsto; a API separa pagamento comprovado de vencimento. |
| Situação (`situacao`) | `status` + `payment_method` + `scheduled` | A tela combina esses dados, por exemplo `paid:pix` ou `scheduled:debit`. |

**Diferenças já existentes no cadastro:** `FinancialEntryCreate` aceita `category_id`, `type`, `description`, `amount`, `due_date` e `appointment_id` opcional. A quitação usa a operação de pagamento existente com `paid_at` e fuso horário, não uma data convertida arbitrariamente para meia-noite UTC. O campo `competence` persistido atualmente é exclusivo de recorrências e representa o primeiro dia do mês; ele não deve receber diretamente `competence_date` de um lançamento avulso. Forma de pagamento e agendamento também não fazem parte do cadastro atual. A extração apenas informa esses dados na prévia; esta US não modifica os contratos de persistência ou cria migrations.

## Regras de interpretação

- Documento e contexto são tratados como dados não confiáveis; o prompt manda ignorar instruções embutidas. A chamada multimodal não disponibiliza ferramentas ou operações de escrita.
- O prompt distingue total final, subtotal, desconto, impostos e parcelas. Não converte outras moedas para BRL nem soma movimentações distintas.
- Nota fiscal não comprova pagamento. `PAID` e `payment_date` são removidos sem confirmação e evidência de liquidação fornecidas pelo modelo. Agendamento não equivale a quitação. A ausência de prova não implica automaticamente `PENDING`.
- Dados sem avaliação ou marcados como desconhecidos são descartados. Não há preenchimento automático com a data atual.
- A IA recebe somente nome da empresa e IDs, nomes e tipos das categorias dessa empresa, consultadas pelo service existente com paginação. Categorias inventadas, de outra empresa ou de tipo incompatível são descartadas. Nenhuma categoria é criada.
- O retorno estruturado usa JSON Schema derivado do Pydantic em modo de serialização, compatível com valor monetário em texto. A resposta é validada pelo Pydantic, inclusive restrições monetárias, datas e enums. JSON livre ou saída incompleta não é aceita.
- Reutiliza timeout, retries limitados, monitoramento de consumo e tradução de erros do provider Gemini. Os logs da integração não incluem arquivo, imagem ou resposta bruta. Não há OCR separado, histórico de documentos nem nova chave de API.

## Erros

| HTTP | Caso |
| --- | --- |
| 401 / 403 | Falha de autenticação, usuário inativo ou sem empresa vinculada. |
| 413 | Arquivo ou corpo multipart excede o limite. |
| 415 | Formato real não suportado ou requisição sem multipart. |
| 422 | Documento vazio/corrompido, limites de complexidade, formulário inválido ou campos extras. |
| 429 | Limite/cota do Gemini. |
| 502 | Resposta do modelo inválida. |
| 503 | Integração Gemini ou consulta financeira indisponível. |
| 504 | Timeout do Gemini. |

Os erros do provider preservam os códigos existentes documentados em [ASSISTANT.md](ASSISTANT.md).

## Configuração e teste manual

Não foram criadas variáveis de ambiente. Configure as existentes: `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_TIMEOUT_MS`, `GEMINI_MAX_OUTPUT_TOKENS`, JWT e conexão PostgreSQL, conforme [ASSISTANT.md](ASSISTANT.md). O modelo configurado deve aceitar imagem/PDF e saída estruturada. Esta extração funciona sem habilitar escritas da assistente.

Em `apps/api/`:

```bash
uv sync --locked
uv run uvicorn app.main:app --reload
```

1. Abra `http://localhost:8000/docs`.
2. Faça login em `POST /api/v1/auth/login` com um usuário existente vinculado à empresa de testes.
3. Use o token em **Authorize**.
4. Abra **Financial document extraction → POST /api/v1/financial/document-extraction → Try it out**.
5. Escolha um JPG/JPEG, PNG ou PDF no campo `file` e clique em **Execute**.
6. Confira resposta, campos nulos, avaliações e avisos. Repita com comprovante pago e nota sem prova de pagamento. Nenhum lançamento deve aparecer apenas pelo envio do documento.

Exemplo equivalente no PowerShell, com token mantido em variável de ambiente:

```powershell
curl.exe -X POST "http://localhost:8000/api/v1/financial/document-extraction" `
  -H "Authorization: Bearer $env:ORGANIZAE_TEST_TOKEN" `
  -F "file=@C:/documentos/comprovante.png"
```

Troque o caminho por `.jpg`, `.jpeg` ou `.pdf` para os outros formatos. Use documentos de teste sem dados pessoais reais. A extração é interpretativa e depende da qualidade do arquivo e da capacidade do modelo; validar estrutura não comprova autenticidade ou exatidão do documento.

## Testes automatizados

```bash
uv run pytest tests/test_financial_document_extraction.py
uv run ruff check .
```

Usam banco isolado em memória, mocks do Gemini e transporte HTTP simulado para conferir a serialização real do SDK. Não consomem tokens, não usam banco de produção e não validam uma chamada real ao Google.
