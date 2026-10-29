# AGENTS.md — Organizaê

## 1. Contexto do projeto

O Organizaê é uma plataforma de gerenciamento e agendamentos para pequenos negócios, como barbearias, salões de beleza e outros prestadores de serviços.

O sistema permite que empresas gerenciem seus serviços, profissionais, clientes e agendamentos.

O projeto é desenvolvido em equipe e utiliza uma arquitetura de monorepo.

## 2. Tecnologias

### Backend
- Python
- FastAPI
- PostgreSQL
- SQLAlchemy 2.x
- Alembic
- Pydantic v2
- uv
- Pytest

### Frontend
- React + Vite para o painel administrativo
- Astro para o site público de agendamentos

Respeite as tecnologias e dependências existentes. Não introduza novos frameworks, bibliotecas ou ferramentas sem necessidade.

## 3. Convenções de código

- Escrever nomes de classes, variáveis, atributos, métodos e funções em inglês.
- Utilizar `snake_case` para variáveis, funções, métodos e arquivos Python.
- Utilizar `PascalCase` para classes.
- Utilizar nomes de tabelas em inglês, no plural e em `snake_case`.
- Utilizar type hints nas funções e métodos Python.
- Seguir as convenções da PEP 8.
- Priorizar código simples, legível, organizado e de fácil manutenção.
- Evitar duplicação de código.
- Não criar abstrações, interfaces ou classes desnecessárias.
- Não adicionar comentários óbvios. Comentar apenas regras ou decisões que precisem de explicação.
- Preservar os padrões já utilizados no projeto.

## 4. Arquitetura do backend

O backend utiliza uma arquitetura modular e em camadas:

`Router → Service → Repository → Database`

Cada módulo pode conter:

- `models.py`: entidades SQLAlchemy e relacionamentos.
- `schemas.py`: schemas Pydantic para entrada e saída de dados.
- `repository.py`: operações de persistência e consulta.
- `service.py`: regras de negócio e coordenação de transações.
- `router.py`: endpoints HTTP e integração com FastAPI.

### Regras das camadas

**Router**
- Receber requisições HTTP.
- Validar parâmetros com Pydantic e FastAPI.
- Chamar os métodos do Service.
- Retornar os códigos HTTP e schemas apropriados.
- Não implementar regras de negócio diretamente.

**Service**
- Concentrar as regras de negócio.
- Coordenar operações entre repositories.
- Gerenciar os limites das transações conforme o padrão do projeto.
- Tratar situações de negócio inválidas com exceções apropriadas.
- Não depender diretamente de `HTTPException` do FastAPI.

**Repository**
- Executar consultas e operações usando SQLAlchemy.
- Não conter regras de negócio.
- Não executar `commit()` ou `rollback()`.
- Respeitar a sessão recebida por injeção de dependências.

**Models**
- Utilizar SQLAlchemy 2.x com `Mapped` e `mapped_column`.
- Manter relacionamentos consistentes com as regras de negócio.
- Evitar importações circulares entre models.
- Utilizar constraints no banco para garantir integridade.

**Schemas**
- Utilizar Pydantic v2.
- Separar schemas de criação, atualização e resposta quando necessário.
- Validar formatos, tipos e limites dos dados.
- Não expor diretamente os models SQLAlchemy como contratos da API.

## 5. Banco de dados

- Utilizar PostgreSQL.
- Gerenciar alterações estruturais exclusivamente por migrations do Alembic.
- Não utilizar `Base.metadata.create_all()` para substituir migrations.
- Não alterar migrations já aplicadas ou compartilhadas sem justificativa explícita.
- Revisar migrations geradas automaticamente antes de aplicá-las.
- Preservar chaves estrangeiras, constraints e integridade referencial.
- Não excluir dados ou tabelas existentes sem autorização.

### Isolamento entre empresas

O Organizaê é uma aplicação multiempresa.

- Cada profissional pertence a uma única empresa.
- Cada serviço pertence a uma única empresa.
- Profissionais só podem ser associados a serviços da própria empresa.
- Dados de uma empresa não devem ser acessíveis por outra.
- Quando houver autenticação, a empresa associada ao usuário deverá ser determinada pelo contexto autenticado, e não confiada diretamente ao cliente.

Essas regras devem ser respeitadas em todas as funcionalidades.

## 6. Tratamento de erros

- Utilizar exceções específicas para erros de negócio.
- Não esconder erros inesperados com `except Exception` indiscriminado.
- Não retornar mensagens internas sensíveis ao cliente.
- Tratar erros de integridade do PostgreSQL adequadamente.
- Não realizar `commit()` quando uma operação de negócio falhar.
- Garantir `rollback()` quando necessário.

## 7. Testes e qualidade

- Criar testes para regras de negócio importantes.
- Utilizar Pytest para testes do backend.
- Cobrir cenários de sucesso e falha.
- Não utilizar bancos de produção em testes.
- Não remover testes existentes para fazer uma implementação passar.
- Executar os testes relevantes após alterações, quando o ambiente permitir.
- Informar quando algum teste não puder ser executado.

Comandos utilizados no backend, a partir de `apps/api/`:

```bash
uv sync --locked
uv run pytest
uv run ruff check .
uv run alembic current
```

## 8. Segurança

- Nunca incluir senhas, tokens ou credenciais diretamente no código.
- Utilizar variáveis de ambiente para configurações sensíveis.
- Nunca enviar o arquivo `.env` ao repositório.
- Não expor dados de outras empresas.
- Validar dados recebidos da API.
- Utilizar consultas parametrizadas e os recursos do SQLAlchemy.
- Não implementar autenticação ou autorização fictícia para contornar regras de segurança.

## 9. Regras para alterações no código

Antes de implementar uma tarefa:

1. Analisar os arquivos existentes relacionados à funcionalidade.
2. Compreender a arquitetura e as regras de negócio.
3. Reutilizar componentes e funções existentes quando apropriado.
4. Identificar possíveis impactos nos demais módulos.

Durante a implementação:

1. Alterar apenas os arquivos necessários.
2. Não refatorar código fora do escopo sem necessidade.
3. Evitar criar funcionalidades que não foram solicitadas.
4. Preservar compatibilidade com os contratos existentes.
5. Não adicionar dependências sem explicar a necessidade.
6. Não executar comandos destrutivos ou alterar dados persistidos sem autorização.

Após a implementação:

1. Resumir as alterações realizadas.
2. Explicar brevemente as principais decisões técnicas.
3. Informar quais arquivos foram criados ou modificados.
4. Relatar os testes executados e seus resultados.
5. Apontar limitações e pendências relevantes.

## 10. Comunicação

- Responder e explicar decisões técnicas em português brasileiro.
- Manter nomes e identificadores do código em inglês.
- Explicar soluções de forma didática e objetiva.
- Priorizar a compreensão do código, pois o projeto também possui finalidade acadêmica.
- Quando existir uma decisão arquitetural importante sem definição, apresentar as alternativas e recomendar uma, sem presumir requisitos de negócio.
- Não afirmar que uma implementação foi testada ou concluída sem verificação.

## 11. Fluxo de trabalho com Git

- Cada história de usuário deve ser desenvolvida em uma branch própria.
- Utilizar nomes de branches descritivos, como `feat/T2-HU001-business-crud`.
- Seguir Conventional Commits.
- Escrever as mensagens de commit em português.
- Não criar commits ou realizar push automaticamente sem solicitação.
- Não alterar a branch principal diretamente.
- Evitar misturar funcionalidades diferentes no mesmo commit.