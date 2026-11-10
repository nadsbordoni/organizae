import { defineTheme } from './base';

/**
 * Exemplo de segunda identidade: trocar a aparência é trocar valores num objeto,
 * sem mudar componente nem duplicar CSS.
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
