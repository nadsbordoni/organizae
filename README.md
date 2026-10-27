# Organizaê

Plataforma de agendamento e gestão para prestadores de serviço, como estúdios de beleza e salões. Cada estúdio tem sua página pública e seu painel, e todos compartilham a mesma aplicação.

> Projeto da faculdade, em fase de planejamento. Ainda não há código da aplicação.

## Arquitetura

```mermaid
flowchart TD
    A["Site publico do studio - Astro"] --> D["API - Spring Boot e Java"]
    B["Painel do prestador - React e Vite"] --> D
    D --> E["PostgreSQL com tenant_id"]
    D --> F["Tarefas agendadas - Quartz ou JobRunr"]
    F --> G["WhatsApp e e-mail"]
```

Os dois front-ends falam com uma API única, e só ela acessa o banco e as tarefas em segundo plano.

## Decisões

| Tema | Escolha | Motivo |
|---|---|---|
| Back-end | Spring Boot, Java 21, Maven | Linguagem e ferramenta mais usadas na faculdade |
| Banco | PostgreSQL | Impede agendamentos sobrepostos direto no banco e oferece Row-Level Security |
| Multi-tenant | Um banco, `tenant_id` em toda tabela | Mais simples de operar com vários estúdios |
| Painel | React + Vite | App logado, sem necessidade de SEO |
| Páginas públicas | Astro | HTML rápido e bom SEO |
| Contrato front/back | OpenAPI gerado pela API | Os tipos do front são gerados a partir dele |
| Tarefas em segundo plano | JobRunr (Postgres) | Lembretes e cobranças sem precisar de Redis |

## Estrutura prevista

```
organizae/
  apps/
    api/        Spring Boot
    painel/     React + Vite
    site/       Astro
  docker-compose.yml   PostgreSQL local
```

## Assistente de IA

A API inclui uma assistente de texto integrada ao Google Gemini para orientar o usuário sobre o Organizaê. Consulte o [guia da assistente](docs/ASSISTANT.md) para configuração, execução, arquitetura, testes e limitações atuais.

## Como contribuir

Antes de subir código, leia o `.env.example` e nunca envie o arquivo `.env`.
