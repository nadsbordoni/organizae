// @ts-check
import { defineConfig } from 'astro/config';
import node from '@astrojs/node';

export default defineConfig({
  // Canonical e imagem de Open Graph saem daqui. ⚠️ TROQUE ao definir o domínio.
  site: 'https://nadsbordoni.github.io/organizae',

  // Páginas públicas são geradas no build; só o painel (`prerender = false`)
  // roda no servidor.
  output: 'static',
  adapter: node({ mode: 'standalone' }),

  trailingSlash: 'ignore',
});
