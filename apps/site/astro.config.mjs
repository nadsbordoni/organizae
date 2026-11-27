// @ts-check
import { defineConfig, envField } from 'astro/config';
import node from '@astrojs/node';

export default defineConfig({
  // Canonical e imagem de Open Graph saem daqui. TROQUE ao definir o domínio.
  site: 'https://nadsbordoni.github.io/organizae',

  // Páginas públicas saem do build; só o painel (`prerender = false`) roda no servidor.
  output: 'static',
  adapter: node({ mode: 'standalone' }),

  trailingSlash: 'ignore',

  env: {
    schema: {
      // Endereço da API (`apps/api`). Sem ela, o painel funciona com os dados de exemplo.
      ORGANIZAE_API_URL: envField.string({ context: 'server', access: 'secret', optional: true }),
    },
  },
});
