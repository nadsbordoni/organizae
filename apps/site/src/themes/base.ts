import type { ThemeTokens, ThemeOverrides } from '@/types/theme';

/** Identidade do Organizaê, medida no protótipo de alta fidelidade. Todo tema herda daqui via `defineTheme()`. */
export const baseTheme: ThemeTokens = {
  color: {
    brand: '#1f1f1f',
    brandDeep: '#000000',
    brandSoft: '#f3eee5',
    onBrand: '#fffdf9',
    surface: '#fffdf9',
    text: '#1f1f1f',
    textMuted: '#726f68',
    border: '#e5dfd5',
    borderStrong: '#ddd5c9',
    eyebrow: '#8b6920',
    // O vermelho do protótipo (#b75b5b) fica abaixo de 4.5:1 em texto pequeno.
    error: '#a63d3d',
  },
  background: {
    page: '#faf6ee',
    pageSolid: '#faf6ee',
    texture: 'none',
  },
  font: {
    // A fonte variável traz o eixo de tamanho óptico: título grande afina sozinho, como no Figma.
    display: "'DM Sans Variable', system-ui, 'Segoe UI', sans-serif",
    body: "'DM Sans Variable', system-ui, 'Segoe UI', sans-serif",
    displayWeight: '400',
    displayTracking: '-0.03em',
  },
  radius: {
    button: '12px',
    card: '20px',
    avatar: '18px',
    field: '12px',
  },
  shadow: {
    resting: '0 1px 2px rgba(31, 31, 31, 0.04)',
    raised: '0 10px 28px rgba(31, 31, 31, 0.08)',
  },
  button: {
    background: 'var(--site-color-surface)',
    color: 'var(--site-color-text)',
    borderColor: 'var(--site-color-border-strong)',
    // NÃO reduza: 48px é o mínimo confortável de área de toque.
    minHeight: '52px',
    // Moldura desligada: 1px é a borda invisível que o botão comum já tem.
    ringGap: '1px',
    ringGapColor: 'transparent',
    ringWidth: '0px',
    ringColor: 'transparent',
  },
  space: {
    pageInline: '20px',
    stack: '12px',
    // Coluna estreita no desktop mantém a sensação de página mobile.
    maxWidth: '560px',
  },
  ornament: {
    // Tamanho zero: no protótipo os itens abaixo do nome não têm separador.
    separator: 'circle(50%)',
    separatorSize: '0px',
  },
  accent: {
    yellow: '#ffd54f',
    yellowSoft: '#f6d868',
    yellowDeep: '#8b6920',
    pink: '#ff80c8',
    pinkSoft: '#f5b8d9',
    pinkDeep: '#a43b76',
    blue: '#7ec8ff',
    blueSoft: '#b6caeb',
    blueDeep: '#456899',
    green: '#9bab64',
    greenDeep: '#536626',
  },
  panel: {
    background: '#faf6ee',
    sidebar: '#1f1f1f',
    onSidebar: '#fffdf9',
    onSidebarMuted: '#aaa8a2',
    sidebarAccent: '#f6d868',
    sidebarActive: '#30302e',
    now: '#e35959',
    info: '#7ec8ff',
    infoSoft: '#dde8f6',
    positive: '#9bab64',
    positiveSoft: '#e7ebd8',
    attention: '#f6d868',
    attentionSoft: '#fbefc4',
    danger: '#ff80c8',
    dangerSoft: '#fbe0ee',
  },
};

/**
 * Grupo a grupo, sem laço genérico: não há cast, e um grupo novo em `ThemeTokens`
 * acusa erro aqui, que é onde ele precisa de um valor padrão.
 */
export function defineTheme(overrides: ThemeOverrides): ThemeTokens {
  return {
    color: { ...baseTheme.color, ...overrides.color },
    background: { ...baseTheme.background, ...overrides.background },
    font: { ...baseTheme.font, ...overrides.font },
    radius: { ...baseTheme.radius, ...overrides.radius },
    shadow: { ...baseTheme.shadow, ...overrides.shadow },
    button: { ...baseTheme.button, ...overrides.button },
    space: { ...baseTheme.space, ...overrides.space },
    ornament: { ...baseTheme.ornament, ...overrides.ornament },
    accent: { ...baseTheme.accent, ...overrides.accent },
    panel: { ...baseTheme.panel, ...overrides.panel },
  };
}
