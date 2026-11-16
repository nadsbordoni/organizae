# Seed operacional

O comando manual `scripts.seed_operational` popula uma **empresa de testes já existente**, identificada por `--business-id`. O seed é opcional e pode usar o próprio banco principal `organizae` quando ele for local e de desenvolvimento; criar um banco separado também é opcional.

## Execução

Use Python 3.12+, as dependências do backend instaladas e um banco com as migrations atuais já aplicadas. O comando não cria empresa, usuário, banco ou tabelas e não executa migrations.

Em `apps/api/`, para usar o banco local:

```powershell
$env:APP_ENV = "development"
$env:DB_NAME = "organizae"
uv run python -m scripts.seed_operational --business-id "<UUID-da-empresa-de-testes>"
```

Substitua o UUID pela empresa que receberá os dados. Host, porta, usuário e senha seguem as configurações existentes de `DB_HOST`, `DB_PORT`, `DB_USER` e `DB_PASSWORD`, lidas do ambiente ou do `.env` da raiz. Variáveis `$env:` do PowerShell têm prioridade sobre o `.env`. Para consultar pela API ou assistente, a API deve usar o mesmo banco e o usuário autenticado deve estar vinculado à empresa escolhida.

A execução exige `APP_ENV=development` ou `test`. O padrão `production` permanece bloqueado antes de abrir a conexão. O script não detecta automaticamente se o servidor é local: a configuração deve apontar para desenvolvimento/testes. O comando manual exige PostgreSQL; SQLite em memória é aceito somente pelos testes automatizados.

## Dados gerados

As quantidades abaixo são do conjunto do seed, além dos dados operacionais que a empresa já possui:

| Registro | Quantidade planejada |
| --- | ---: |
| Profissionais ativos | 6 |
| Categorias de serviços | 4 |
| Serviços ativos | 12 |
| Vínculos em `professional_services` | 36 |
| Clientes fictícios | 80 |
| Agendamentos | 200 |
| Bloqueios adicionais de agenda | 6 |

As categorias de serviços são **Cortes**, **Barba**, **Tratamentos** e **Combos**, com o prefixo de identificação do seed. São registros da tabela `categories`, separados das categorias financeiras.

Serviços têm preços entre R$ 15 e R$ 120 e durações de 15, 30, 45, 60, 90 e 120 minutos. Cada profissional atende seis serviços, com distribuição que contempla todo o catálogo.

O cenário padrão distribui 100 agendamentos antes e 100 depois da data de referência. São 120 `CONFIRMED`, 40 `PENDING` e 40 `CANCELLED`, além dos seis `BLOCKED`, um deles para toda a empresa. Esses são os status existentes na modelagem; não há status de atendimento concluído. Os registros usam origem `PANEL`.

Os clientes usam nomes identificados como fictícios, e-mails em `example.com` e telefones sintéticos com prefixo `000`. Colisões com telefones existentes na mesma empresa recebem outro número sintético, sem reutilizar ou alterar o cadastro anterior.

## Horários e disponibilidade

Se a empresa não tem nenhum horário comercial cadastrado, o seed cria segunda a sábado, das 09h às 12h e das 13h às 18h. Se já existem horários, preserva toda a configuração, inclusive dias fechados e intervalos.

A modelagem atual não possui tabela de jornadas individuais de profissionais. A disponibilidade é calculada pelo `AppointmentService` a partir dos horários da empresa, vínculo profissional/serviço, duração e agendamentos ou bloqueios existentes.

O seed reutiliza os Services de categorias, serviços, profissionais, clientes e agenda. Os agendamentos passam por `book_panel`, as confirmações/cancelamentos por `update_status` e os bloqueios por `create_block`. Vínculos ausentes são validados e adicionados sem remover associações existentes. Não há alteração nas regras de negócio.

A primeira execução usa a data local de `BUSINESS_TIMEZONE` como referência. Os dias preferenciais ficam até 45 dias antes ou depois dessa data; a busca pode avançar até 59 dias adicionais no mesmo sentido para encontrar espaço. As datas futuras respeitam a janela de 120 dias do Service. Para criar histórico passado, o seed usa o argumento `now` já existente no Service como relógio histórico de criação, mantendo as validações de disponibilidade e o limite de agendamentos por telefone.

Horários sem espaço ou profissionais/serviços do seed desativados não são forçados. O JSON de saída informa os contadores `created` e as chaves não criadas em `unavailable`. Nesses casos as quantidades podem ser menores que o planejado; uma reexecução tenta preencher apenas os itens ainda ausentes.

## Identificação, reexecução e segurança

Os registros são identificados por **`[SEED-OPS-V1]`** nos nomes, descrições ou observações, e por UUIDs determinísticos separados por empresa. Clientes e agendamentos registram a data de referência e o fuso nas observações. Os horários comerciais padrão têm IDs determinísticos, pois esse model não possui campo de observações.

A referência é reaproveitada nas próximas execuções: os registros não mudam de data e uma nova execução em outro dia não cria outro conjunto. Preserve esses metadados. Se houver referências incompatíveis ou mudança de fuso, o comando recusa a execução sem alterar dados.

Somente registros e vínculos ausentes são criados. Nas reexecuções, o seed também preenche `category_id` vazio nos serviços identificados pelos seus UUIDs determinísticos, permitindo completar dados gerados pela versão anterior. Serviços fora do seed e categorias já atribuídas são preservados, assim como valores, nomes e status alterados manualmente. Categorias com o mesmo nome reservado já existentes na empresa são reutilizadas sem distinção de maiúsculas e minúsculas. O script não reativa profissionais ou serviços desativados. Uma reexecução intacta informa zero em todos os campos de `created` e em `linked_existing_services`, que conta os serviços existentes do seed que receberam uma categoria antes ausente.

Para completar as categorias de um seed já executado, repita o mesmo comando com o mesmo `--business-id`. Não é necessário apagar dados, executar o seed financeiro nem aplicar migrations adicionais.

A execução mantém uma única transação externa e bloqueia a empresa com o mesmo mecanismo usado pela agenda. Os commits internos dos Services não confirmam parcialmente o lote; se ocorrer uma falha, as inserções e associações preenchidas naquela tentativa são revertidas.

**O seed operacional não consulta nem escreve em `FinancialEntry`, `FinancialCategory` ou `RecurringEntry`, não executa o seed financeiro e não cria vínculos financeiros com agendamentos.** Não há execução no startup, migrations, commits Git ou push automáticos.

## Validação

```powershell
uv run pytest tests/test_seed_operational.py -p no:cacheprovider
uv run ruff check scripts/seed_operational.py tests/test_seed_operational.py
```

Os testes usam SQLite descartável em memória, com conversão de timestamps para reproduzir o armazenamento UTC do PostgreSQL. Exercitam Services e Repositories reais, relações, duração, disponibilidade, conflitos, isolamento, reexecução em outro dia, reposição de itens faltantes, preservação de dados, bloqueio de produção e rollback mesmo após commits internos. Também rejeitam qualquer SQL do seed nas três tabelas financeiras e verificam que registros financeiros preexistentes ficam intactos.
