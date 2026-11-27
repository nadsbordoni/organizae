# apps/site

As telas do Organizaê feitas até agora: páginas públicas de cada estúdio, o fluxo de agendamento e um **protótipo do painel**.

```bash
npm install
npm run dev     # http://localhost:4321
npm run check   # tipos
npm run build   # confere o lockfile, os tipos e gera dist/
```

## O que existe

| Rota | Tela |
|---|---|
| `/` e `/exemplo` | Página de links do estúdio, montada a partir de um arquivo de configuração |
| `/exemplo/produtos` | Vitrine de produtos do estúdio |
| `/exemplo/agendar` | Escolha de serviço, dia e horário, revisão e envio do pedido |
| `/painel` | Visão geral: números do mês, movimento financeiro e agenda de hoje |
| `/painel/agenda` | Grade da semana no computador; no celular, os 7 dias e o dia escolhido. Tocar numa marcação abre os detalhes |
| `/painel/login` | Entrada do painel |

Cada estúdio é um arquivo em `src/config/sites/`. Para ver o formato, comece por `_exemplo.ts`. O visual vem de um tema em `src/themes/`: `base.ts` é a identidade do Organizaê, e `indigo.ts` mostra como fazer um tema próprio.

## Com a API

Sem configuração, o painel funciona sozinho, com os dados de exemplo de `src/lib/dados-exemplo.ts`, bom para apresentar. Para ligar à API (`apps/api`), suba a API e informe o endereço:

```bash
docker compose up -d db migrate api              # na raiz do projeto
ORGANIZAE_API_URL=http://localhost:8000 npm run dev
```

Pelo `compose.yaml`, o serviço `frontend` já recebe o endereço da API.

O navegador nunca fala com a API: o servidor do Astro faz as chamadas (`src/lib/api.ts`) e guarda o token num cookie `HttpOnly` (`src/lib/session.ts`). O `src/middleware.ts` protege o painel e manda para o login quem não tem sessão.

O que já vem da API:

- **Login e sair** (`/api/login`, `/api/logout`), e o nome de quem entrou, por `GET /users/me`.

O resto do painel ainda usa os dados de exemplo e passa para a API aos poucos.

## O que ainda é provisório

- **Telas ainda não ligadas à API** usam os dados de exemplo, mesmo com a API configurada.
- **Busca, "Novo agendamento", "Importar nota" e o envio de campanhas** aparecem como no protótipo, mas ainda não fazem nada.
- **O agendamento público calcula os horários livres, mas não reserva.** O pedido sai por WhatsApp, e o número no `_exemplo.ts` é fictício.
- **Em produção**, com domínio próprio, falta configurar `security.allowedDomains` no `astro.config.mjs`: sem isso, o Astro recusa os formulários enviados de um endereço diferente de `localhost`.

## Dependências

`package-lock.json` deve apontar só para o registro público do npm. Depois de qualquer `npm install`, rode `npm run lockfile:publico`. O `npm run build` falha se sobrar endereço de outro registro.
