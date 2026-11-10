/**
 * Tema = objeto de tokens que vira CSS custom properties (`toCssVars.ts`) no elemento raiz.
 * Nenhum componente conhece cor de cliente: todos leem `var(--site-*)`.
 */

export interface ThemeTokens {
  color: {
    brand: string;
    /** Mais escura: hover, pressed, texto de destaque. */
    brandDeep: string;
    /** Mais clara: fundo suave, borda, estado sutil. */
    brandSoft: string;
    /** Vai SOBRE `brand`. Precisa contrastar com ela. */
    onBrand: string;
    /** Fundo de card e botão secundário. */
    surface: string;
    text: string;
    /** Texto secundário. Contraste mínimo de 4.5:1. */
    textMuted: string;
    /** Contorno de cartão. */
    border: string;
    /** Contorno de campo e de linha clicável, um tom acima de `border`. */
    borderStrong: string;
    /** Sobretítulo em caixa alta acima dos títulos. Contraste mínimo de 4.5:1. */
    eyebrow: string;
  };

  background: {
    /** Cor sólida ou gradiente. */
    page: string;
    /** Sólida, para `theme-color` e fallback. */
    pageSolid: string;
    /**
     * Textura em tile POR CIMA do gradiente, com `background-size: auto`: um SVG com
     * `width`/`height` e sem `viewBox` define o azulejo. `none` (padrão) desliga.
     */
    texture: string;
  };

  font: {
    /**
     * Nome do negócio e título de cada página interna. Em fonte subsetada, o subset
     * PRECISA incluir esses títulos, não só o wordmark.
     */
    display: string;
    body: string;
    displayWeight: string;
    /** `letter-spacing` dos títulos. Negativo aperta, como no protótipo. */
    displayTracking: string;
  };

  radius: {
    button: string;
    card: string;
    avatar: string;
    /**
     * Campo de formulário e peças pequenas selecionáveis. Separado de `card` porque, com
     * raio de pill (999px), uma caixa de texto vira cápsula e deixa de parecer campo.
     */
    field: string;
  };

  shadow: {
    resting: string;
    raised: string;
  };

  /**
   * Botão comum (sem `emphasis: 'primary'`). Aceita outros tokens, ex.
   * `'var(--site-color-brand-soft)'`: todos viram custom properties no mesmo elemento.
   */
  button: {
    background: string;
    color: string;
    /** `transparent` para botão sem contorno. */
    borderColor: string;
    /** Área de toque. NUNCA abaixo de 48px. */
    minHeight: string;

    /**
     * Moldura do botão PRINCIPAL: respiro desenhado como borda e fio como sombra externa,
     * então nada muda de tamanho. Padrão inerte: respiro = borda invisível, fio zero.
     */
    ringGap: string;
    /** Cor do respiro. Normalmente o que está ATRÁS do botão. */
    ringGapColor: string;
    ringWidth: string;
    ringColor: string;
  };

  space: {
    pageInline: string;
    /** Espaço vertical entre blocos. */
    stack: string;
    maxWidth: string;
  };

  /**
   * Separador de lista como FORMA (`clip-path` sobre um quadrado), NÃO caractere: glifo que
   * faltasse na fonte cairia no emoji colorido do sistema e estouraria a paleta.
   */
  ornament: {
    /** `clip-path` da marca. `circle(50%)` dá o ponto de sempre. */
    separator: string;
    /** Lado do quadrado antes do corte. */
    separatorSize: string;
  };

  /**
   * Cores de apoio, para alerta e detalhe; a ação principal é sempre `brand`. Texto sobre a
   * forte e a `Soft` é `color.text`. A `Deep` é para TEXTO colorido: contraste mínimo de 4.5:1.
   */
  accent: {
    yellow: string;
    yellowSoft: string;
    yellowDeep: string;
    pink: string;
    pinkSoft: string;
    pinkDeep: string;
    blue: string;
    blueSoft: string;
    blueDeep: string;
    green: string;
    greenDeep: string;
  };

  /**
   * Só o painel usa. Cada estado tem a forte (ícone, barra) e a suave (fundo do selo);
   * o texto por cima das duas é `color.text`: confira o contraste ao trocar.
   */
  panel: {
    /** Fundo da área de conteúdo. */
    background: string;
    sidebar: string;
    onSidebar: string;
    /** Texto secundário no menu. Contraste mínimo de 4.5:1. */
    onSidebarMuted: string;
    /** Ícone do item ativo. */
    sidebarAccent: string;
    /** Fundo do item ativo e do cartão de ajuda. */
    sidebarActive: string;
    /** Linha da hora atual na grade da semana. */
    now: string;
    /** Confirmado, faturamento. */
    info: string;
    infoSoft: string;
    /** Valor recebido. */
    positive: string;
    positiveSoft: string;
    /** A confirmar, a receber, vencendo. */
    attention: string;
    attentionSoft: string;
    /** Em atraso. */
    danger: string;
    dangerSoft: string;
  };
}

/** `defineTheme()` completa o resto a partir do base. */
export type ThemeOverrides = {
  [K in keyof ThemeTokens]?: Partial<ThemeTokens[K]>;
};
