import type { ThemeTokens, ThemeOverrides } from '@/types/theme';

/**
 * Tema base — neutro e acessível. Todo tema herda daqui via `defineTheme()`,
 * então um tema novo só precisa declarar o que muda.
 */
export const baseTheme: ThemeTokens = {
  color: {
    brand: '#1f2937',
    brandDeep: '#111827',
    brandSoft: '#f3f4f6',
    onBrand: '#ffffff',
    surface: '#ffffff',
    text: '#111827',
    textMuted: '#4b5563',
    border: '#e5e7eb',
  },
  background: {
    page: '#f9fafb',
    pageSolid: '#f9fafb',
    texture: 'none',
  },
  font: {
    // Fallback do sistema: 0 KB. Cada marca traz a sua no próprio tema,
    // declarando a própria @font-face.
    display: "Georgia, 'Times New Roman', serif",
    body: "'Jost Variable', system-ui, 'Segoe UI', sans-serif",
  },
  radius: {
    button: '16px',
    card: '20px',
    avatar: '50%',
    field: '14px',
  },
  shadow: {
    resting: '0 1px 2px rgba(17, 24, 39, 0.06)',
    raised: '0 6px 18px rgba(17, 24, 39, 0.12)',
  },
  button: {
    background: 'var(--site-color-surface)',
    color: 'var(--site-color-text)',
    borderColor: 'var(--site-color-border)',
    // 48px é o mínimo confortável de área de toque. Não reduza.
    minHeight: '56px',
    // Moldura desligada: 1.5px é a mesma borda invisível que o botão comum já
    // tinha, e o fio externo não existe.
    ringGap: '1.5px',
    ringGapColor: 'transparent',
    ringWidth: '0px',
    ringColor: 'transparent',
  },
  space: {
    pageInline: '20px',
    stack: '12px',
    // Coluna estreita no desktop mantém a sensação de página mobile.
    maxWidth: '520px',
  },
  ornament: {
    separator: 'circle(50%)',
    separatorSize: '4px',
  },
  panel: {
    background: '#f7f7f8',
    sidebar: '#111827',
    onSidebar: '#f3f4f6',
    onSidebarMuted: '#d1d5db',
    sidebarAccent: '#ffffff',
    info: '#93c5fd',
    infoSoft: '#e0eefe',
    positive: '#86d7a8',
    positiveSoft: '#e3f6ea',
    attention: '#fcd34d',
    attentionSoft: '#fef3c7',
    danger: '#f9a19a',
    dangerSoft: '#fde7e4',
  },
};

/**
 * Cria um tema completo a partir de sobrescritas parciais.
 *
 * Escrito grupo a grupo em vez de num laço genérico: assim não há nenhum
 * cast, e adicionar um grupo novo em `ThemeTokens` acusa erro aqui — que é
 * onde queremos ser lembrados de dar um valor padrão a ele.
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
    panel: { ...baseTheme.panel, ...overrides.panel },
  };
}
