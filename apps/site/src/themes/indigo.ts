import { defineTheme } from './base';

/**
 * Tema Índigo — exemplo de segunda identidade visual.
 *
 * Existe para provar (e documentar) que trocar a aparência de uma página
 * inteira é trocar valores num objeto: nenhum componente muda, nenhum CSS
 * é duplicado. Um tema verde/bege/marrom seria igualmente ~20 linhas.
 */
export const indigoTheme = defineTheme({
  color: {
    brand: '#2f4bd8',
    brandDeep: '#1f34a8',
    brandSoft: '#e5e9ff',
    onBrand: '#ffffff',
    surface: '#ffffff',
    text: '#111426',
    textMuted: '#4a5069',
    border: '#e2e5f0',
  },
  background: {
    page: 'linear-gradient(180deg, #f7f8fc 0%, #eceffb 100%)',
    pageSolid: '#f7f8fc',
  },
  radius: {
    button: '14px',
    card: '16px',
  },
  shadow: {
    resting: '0 1px 3px rgba(17, 20, 38, 0.08)',
    raised: '0 8px 22px rgba(17, 20, 38, 0.14)',
  },
});
