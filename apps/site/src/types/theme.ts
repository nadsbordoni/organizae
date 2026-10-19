/**
 * Contrato de tema.
 *
 * Um tema é só um objeto de tokens. Ele vira CSS custom properties (ver
 * `toCssVars.ts`) aplicadas no elemento raiz. Nenhum componente conhece cor de
 * cliente algum — todos leem `var(--site-*)`.
 *
 * Para criar um tema: parta de `base.ts` e sobrescreva o que quiser.
 */

export interface ThemeTokens {
  color: {
    brand: string;
    /** Mais escura — hover, pressed, texto de destaque. */
    brandDeep: string;
    /** Mais clara — fundo suave, borda, estado sutil. */
    brandSoft: string;
    /** Vai SOBRE `brand`. Precisa contrastar com ela. */
    onBrand: string;
    /** Fundo de card e botão secundário. */
    surface: string;
    text: string;
    /** Texto secundário. Contraste mínimo de 4.5:1. */
    textMuted: string;
    border: string;
  };

  background: {
    /** Cor sólida ou gradiente. */
    page: string;
    /** Sólida, para `theme-color` e fallback. */
    pageSolid: string;
    /**
     * Camada de textura POR CIMA do gradiente — grão, papel, trama.
     *
     * Um `background-image` que se repete (tile). O tamanho vem do próprio
     * arquivo: a camada é desenhada com `background-size: auto`, então um SVG
     * com `width`/`height` e sem `viewBox` manda no tamanho do azulejo.
     *
     * `none` desliga. É o padrão: gradiente liso é o que a maioria das marcas
     * quer, e textura é decisão de identidade, não de plataforma.
     */
    texture: string;
  };

  font: {
    /**
     * Títulos: o nome do negócio e o título de cada página interna.
     *
     * Precisa cobrir esses textos, não só o wordmark. Num tema que usa fonte
     * subsetada (fonte de marca de um cliente), o subset tem de
     * incluir os títulos.
     */
    display: string;
    /** Todo o resto do texto. */
    body: string;
  };

  radius: {
    button: string;
    card: string;
    avatar: string;
    /**
     * Campo de formulário e peças pequenas selecionáveis.
     *
     * Separado de `card` porque num tema de canto muito redondo (o pill de 999px,
     * por exemplo) uma caixa de texto com o mesmo raio vira uma
     * cápsula e deixa de parecer campo.
     */
    field: string;
  };

  shadow: {
    resting: string;
    raised: string;
  };

  /**
   * Botão comum (sem `emphasis: 'primary'`).
   *
   * Os valores podem referenciar outros tokens — ex.
   * `background: 'var(--site-color-brand-soft)'` — porque todos viram custom
   * properties no mesmo elemento. É assim que se alterna entre cartão branco,
   * preenchido suave e só contorno, sem enum e sem tocar no componente.
   */
  button: {
    background: string;
    color: string;
    /** `transparent` para botão sem contorno. */
    borderColor: string;
    /** Área de toque. NUNCA abaixo de 48px. */
    minHeight: string;

    /**
     * Moldura do botão PRINCIPAL: preenchimento, respiro, e fio em volta.
     *
     * Serve a marcas cujo botão não é um retângulo cheio, e sim um cheio com um
     * fio afastado dele — é o CTA de algumas artes de marca. O respiro é
     * desenhado como borda (na cor de quem está atrás) e o fio como sombra
     * externa, então nada muda de tamanho na tela.
     *
     * Padrão inerte: o respiro é a borda invisível que o botão já tinha, e o
     * fio tem espessura zero. Tema que não declara nada continua com botão
     * chapado.
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
    /** Largura máxima da coluna no desktop. */
    maxWidth: string;
  };

  /**
   * Marca gráfica da identidade, onde a lista precisa de um separador.
   *
   * É uma FORMA, não um caractere: um `clip-path` desenhado sobre um quadrado
   * na cor da marca. Glifo dependeria de a fonte do corpo ter aquele símbolo, e
   * um coração ou uma estrela que faltasse cairia no emoji colorido do sistema
   * — que estoura a paleta inteira.
   */
  ornament: {
    /** `clip-path` da marca. `circle(50%)` dá o ponto de sempre. */
    separator: string;
    /** Lado do quadrado antes do corte. */
    separatorSize: string;
  };

  /**
   * Painel da dona do negócio. O site público não usa.
   *
   * Cada cor de estado tem a forte (ícone, barra) e a suave (fundo do selo). O
   * texto por cima das duas é `color.text`: confira o contraste ao trocar.
   */
  panel: {
    /** Fundo da área de conteúdo. */
    background: string;
    /** Menu lateral. */
    sidebar: string;
    onSidebar: string;
    /** Texto secundário no menu. Contraste mínimo de 4.5:1. */
    onSidebarMuted: string;
    /** Item ativo e botão de recolher. */
    sidebarAccent: string;
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

/** Tema parcial. `defineTheme()` completa o resto a partir do base. */
export type ThemeOverrides = {
  [K in keyof ThemeTokens]?: Partial<ThemeTokens[K]>;
};
