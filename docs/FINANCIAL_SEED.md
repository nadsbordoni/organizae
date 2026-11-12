# Seed financeiro para testar a assistente

O comando manual `scripts.seed_financial` cria um cenário fictício de barbearia na **empresa de testes informada por parâmetro**. Reutiliza models, enums, schemas e vínculos financeiros existentes, sem migrations, dependências novas ou execução no startup.

## Execução

**O seed e a criação de um banco separado são opcionais.** Se o banco principal `organizae` estiver rodando localmente para desenvolvimento, você pode popular uma empresa de testes nele. Um banco separado é uma alternativa para quem prefere separar também o armazenamento dos dados fictícios.

A partir de `apps/api/`, com as dependências instaladas, consulte primeiro a prévia:

```powershell
uv run python -m scripts.seed_financial --preview
```

A prévia mostra quantidades e totais sem carregar configurações de conexão nem acessar o banco.

Para inserir, o PostgreSQL escolhido precisa ter as migrations atuais aplicadas e uma empresa exclusiva para testes já cadastrada. Configure `DB_HOST`, `DB_PORT`, `DB_USER` e `DB_PASSWORD` pelo ambiente ou pelo `.env` da raiz, seguindo a configuração existente. O comando não cria o banco, as tabelas, usuários ou empresas.

Para usar o próprio banco local, mantenha no `.env`:

```dotenv
DB_NAME=organizae
APP_ENV=development
```

Execute manualmente, substituindo o UUID pelo identificador da empresa de testes nesse banco:

```powershell
$env:APP_ENV = "development"
$env:DB_NAME = "organizae"
uv run python -m scripts.seed_financial --business-id "<UUID-da-empresa-de-testes>"
```

Variáveis definidas com `$env:` têm prioridade sobre o `.env` durante a sessão do PowerShell. Se antes você apontou para outro banco, ajuste `$env:DB_NAME` como no exemplo. A API também precisa usar o mesmo banco; reinicie-a após alterar a configuração.

Como alternativa, crie um banco separado no PostgreSQL de desenvolvimento/testes, aplique as migrations nele, cadastre a empresa de testes e use seu nome em `DB_NAME`, por exemplo `organizae_dev_local` ou `organizae_test`. Não é necessário criar outro banco para usar o seed no `organizae` local existente.

`APP_ENV` deve ser `development` ou `test`; o padrão `production` permanece bloqueado, inclusive para `organizae`. Os nomes permitidos são `organizae`, `organizae_dev` ou `organizae_test`; os dois últimos aceitam sufixo com `_` e letras, números ou underscores. O script valida o ambiente e o nome do banco configurado e da sessão efetiva; não verifica automaticamente se o servidor é local. A permissão para `organizae` destina-se ao banco local de desenvolvimento.

As datas de pagamento usam `BUSINESS_TIMEZONE` (padrão `America/Sao_Paulo`) e são armazenadas em UTC. A execução exige data local a partir de **12/11/2026**, evitando pagamentos futuros. Não é necessário configurar uma chave Gemini para popular os dados.

Para consultar pelo Swagger, faça login com um usuário associado à mesma empresa de testes. O JWT continua determinando a empresa consultada pela assistente; o seed não altera autenticação.

## Dados e identificação

Todos os nomes de categorias e descrições gerados começam com **`[SEED-FIN-2026-V1]`**. Os IDs são determinísticos e separados por empresa. O resultado do comando informa `business_id`, `created` e `preserved`.

- **9 categorias:** serviços, produtos e outras receitas; aluguel, energia, internet, materiais, manutenção e software.
- **182 lançamentos**, 26 por mês, de maio a novembro de 2026: 140 avulsos e **42 ocorrências incluídas no total**.
- **6 recorrências mensais**, vigentes de 01/05 a 30/11: aluguel R$ 1.800, energia R$ 320, internet R$ 120, materiais R$ 450, manutenção R$ 180 e software R$ 90.
- **146 pagos, 22 pendentes e 14 cancelados**. Receitas de serviços/produtos são lotes agregados fictícios, sem clientes ou agendamentos reais.

Cada ocorrência tem `recurring_entry_id` e `competence` no primeiro dia do mês. Gerar novamente as competências pelo Service existente ignora as 42 já presentes: os templates de recorrência não são despesas adicionais. Pagos possuem `paid_at`; pendentes e cancelados não possuem pagamento. Valores usam `Decimal`, sem aleatoriedade.

## Totais esperados

Valores em reais, **somente para os registros do seed**. Recebidos/pagos usam a data local de `paid_at`; pendentes usam `due_date`. Cancelados ficam fora dos relatórios. Saldo = recebido − despesas pagas.

| Mês/2026 | Recebido | Despesas pagas | Saldo realizado | Receitas pendentes | Despesas pendentes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Maio | 6.000,00 | 3.260,00 | 2.740,00 | 600,00 | 0,00 |
| Junho | 7.500,00 | 3.260,00 | 4.240,00 | 750,00 | 0,00 |
| Julho | 9.000,00 | 3.260,00 | 5.740,00 | 900,00 | 0,00 |
| Agosto | 6.300,00 | 3.340,00 | 2.960,00 | 1.050,00 | 320,00 |
| Setembro | 3.000,00 | 4.340,00 | −1.340,00 | 1.200,00 | 120,00 |
| Outubro | 4.200,00 | 3.460,00 | 740,00 | 1.350,00 | 500,00 |
| Novembro | 1.800,00 | 2.640,00 | −840,00 | 2.000,00 | 1.070,00 |
| **Total** | **37.800,00** | **23.560,00** | **14.240,00** | **7.850,00** | **2.010,00** |

Cenários para validar: receitas crescem 25% de maio para junho e 20% de junho para julho; caem **30% de julho para agosto**. Setembro e novembro têm saldo e margem financeira negativos. Outubro tem margem de **17,62%** sobre receitas recebidas.

O cenário é uma fotografia de **12/11/2026**: novembro é parcial, com pagamentos somente até o dia 11 e vencimentos futuros pendentes. Nessa referência há **R$ 1.260,00 em despesas vencidas** (`PENDING`, `due_date < 12/11/2026`); vencimentos do próprio dia não entram como vencidos. A situação de atraso muda com a data real, mas os dados e totais mensais permanecem iguais.

Use períodos explícitos, por exemplo “Quanto recebi em julho de 2026?” ou “Qual minha margem financeira em outubro de 2026?”. Consultas relativas, como “este mês”, seguem o relógio real. Dados que já existam na empresa também entram nos relatórios normais; para comparar exatamente a tabela, use uma empresa de testes sem outros lançamentos ou filtre pelas categorias do seed.

## Reexecução e segurança

A operação é uma única transação, bloqueia a empresa durante o seed e só insere registros ausentes. Não apaga nem atualiza registros existentes. Categorias, recorrências e lançamentos compatíveis são reutilizados, inclusive ocorrências com outro ID mas a mesma recorrência/competência.

Se um registro reservado do seed tiver sido alterado (valor, status, categoria etc.), o comando recusa a execução e desfaz as novas inserções daquela tentativa. Ele preserva o registro alterado; não tenta restaurá-lo nem gerar uma duplicata. Use outra empresa de testes para obter novamente o cenário original. Falhas de integridade também revertem a transação. Empresas diferentes recebem IDs diferentes e dados independentes.

A reexecução intacta deve informar zero em todos os campos de `created`, preservando 9 categorias, 6 recorrências e 182 lançamentos. Nenhum comando de limpeza é incluído.

## Testes

```powershell
uv run pytest tests/test_seed_financial.py -p no:cacheprovider
uv run ruff check scripts tests/test_seed_financial.py
```

Os testes usam SQLite descartável em memória, com o adaptador de fuso já usado pelos testes financeiros. Validam os totais pelos Services reais, vínculos de recorrência, ausência de duplicatas, isolamento, bloqueio de produção, preservação de alterações e rollback. Essa exceção SQLite existe apenas para testes; a execução manual exige PostgreSQL.
