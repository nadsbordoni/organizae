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
| `/exemplo/agendar` | Escolha de serviço, dia e horário, revisão e envio do pedido |
| `/painel` | Home do painel: resumo do dia e próximas clientes |
| `/painel/agenda` | Agenda de um dia, com navegação entre dias |
| `/painel/login` | Entrada do painel |

Cada estúdio é um arquivo em `src/config/sites/`. Para ver o formato, comece por `_exemplo.ts`. O visual de cada um vem de um tema em `src/themes/`.

## O que ainda é provisório

- **O painel usa dados fictícios** de `src/lib/dados-exemplo.ts`. Não há banco nem API.
- **O login não autentica.** Qualquer envio abre o painel.
- **Fechar e reabrir um dia** (botões da agenda) não faz nada ainda: falta o endpoint na API.
- **O agendamento público calcula os horários livres, mas não reserva.** O pedido sai por WhatsApp, e o número no `_exemplo.ts` é fictício.

Quando a API em Spring Boot existir, o painel passa a consumi-la no lugar de `dados-exemplo.ts`, e o painel pode ser reescrito em React (ver o README da raiz).

## Dependências

`package-lock.json` deve apontar só para o registro público do npm. Depois de qualquer `npm install`, rode `npm run lockfile:publico`. O `npm run build` falha se sobrar endereço de outro registro.
