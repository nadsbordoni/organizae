/**
 * Tipos de bloco.
 *
 * A página é uma LISTA ORDENADA de blocos: a ordem no array é a ordem na tela.
 * Cada bloco é um membro da união `Block`, identificado por `type`.
 *
 * PARA ADICIONAR UM TIPO: crie a interface aqui, inclua na união `Block` no
 * fim do arquivo, crie o componente em `src/blocks/` e registre no REGISTRY de
 * `blocks/BlockList.astro`. Esquecer o registro quebra o build, não a produção.
 *
 * ANTES DE CRIAR UM TIPO NOVO: veja se um `link` com props diferentes resolve.
 * Link com ícone, com imagem, com subtítulo e "achadinhos" são todos o mesmo
 * bloco. Só ganha tipo próprio quem tem ESTRUTURA diferente.
 */

/** Ícones disponíveis. Ver `src/components/Icon.astro`. */
export type IconName =
  | 'calendar'
  | 'whatsapp'
  | 'sparkles'
  | 'pin'
  | 'bag'
  | 'heart'
  | 'star'
  | 'phone'
  | 'mail'
  | 'link'
  | 'clock'
  | 'hourglass'
  | 'tag'
  | 'check'
  | 'close'
  | 'alert'
  | 'rules'
  | 'chevron-left'
  | 'chevron-right'
  | 'home'
  | 'trend'
  | 'check-circle'
  | 'alert-circle'
  | 'logout'
  | 'instagram'
  | 'tiktok'
  | 'facebook'
  | 'youtube';

/** Redes sociais suportadas. A URL e o rótulo são derivados do handle. */
export type SocialNetwork =
  | 'instagram'
  | 'tiktok'
  | 'facebook'
  | 'youtube'
  | 'whatsapp';

interface BlockBase {
  /** Linha menor de apoio, abaixo do título. */
  subtitle?: string;
  /**
   * Esconde o bloco sem apagar a configuração — promoção sazonal, serviço em
   * pausa, link que caiu. Volta trocando uma palavra.
   */
  hidden?: boolean;
}

/**
 * Botão de link — o bloco mais usado. Cobre link simples, com ícone, com
 * imagem, agendamento, produto, achadinhos e contato. Tudo via props.
 */
export interface LinkBlock extends BlockBase {
  type: 'link';
  title: string;
  icon?: IconName;
  /** Miniatura à esquerda. Substitui o ícone quando presente. */
  image?: { src: string; alt: string };
  href: string;
  /**
   * `primary` destaca o botão. Use em NO MÁXIMO um ou dois blocos — se tudo é
   * destaque, nada é.
   */
  emphasis?: 'primary' | 'default';
  /** Força nova aba. Por padrão, link externo já abre em nova aba. */
  external?: boolean;
  /**
   * Link que dá comissão. Marca o `rel` como `sponsored` e OBRIGA a página a
   * ter `disclosure` — sem ele o build quebra. Ver `lib/disclosure.ts`.
   */
  affiliate?: boolean;
}

/** Atalho para WhatsApp, com a mensagem inicial já preenchida. */
export interface WhatsappBlock extends BlockBase {
  type: 'whatsapp';
  title: string;
  /** Só dígitos, com DDI e DDD. Ex: '5511999998888'. */
  phone: string;
  /**
   * Mensagem já digitada na conversa. Emoji é removido ao montar a URL — o
   * WhatsApp não preenche a mensagem quando tem. Ver `whatsappUrl()`.
   */
  message?: string;
  emphasis?: 'primary' | 'default';
}

/** Endereço com link para o mapa, e opcionalmente o mapa embutido. */
export interface LocationBlock extends BlockBase {
  type: 'location';
  title: string;
  /** Endereço mostrado na tela, em linhas. */
  address: string[];
  mapsUrl: string;
  /**
   * Mapa embutido. `true` deriva a busca do `address`; uma string usa o `src`
   * de "Compartilhar → Incorporar um mapa" do Google, que é mais preciso.
   *
   * ⚠️ CUSTA CARO: o iframe baixa ~1 MB e roda JavaScript de terceiro. É
   * `lazy`, então só carrega se a pessoa rolar até ele — mas quando carrega,
   * é o item mais pesado da página.
   */
  map?: boolean | string;
  /**
   * O que buscar no mapa quando `map: true`. Aceita "lat,long". Útil quando o
   * `address` tem pontuação que atrapalha a geocodificação.
   */
  mapQuery?: string;
}

/**
 * Horário de funcionamento.
 *
 * Bloco próprio, e não campo da localização: um negócio pode ter horário sem
 * endereço fixo (domicílio, online).
 */
export interface HoursBlock extends BlockBase {
  type: 'hours';
  /** Padrão: 'Horário de atendimento'. */
  title?: string;
  /**
   * Ex: `{ days: 'Ter a Sex', time: '08:00 às 19:30' }`.
   *
   * OMITA quando o site tiver `agenda`: o texto passa a ser derivado dela por
   * `resolveBlocks()`, e o expediente anunciado nunca diverge do agendável.
   * Preencher à mão aqui SOBRESCREVE o derivado — use só quando o horário de
   * porta aberta for diferente do horário de hora marcada.
   */
  schedule?: Array<{ days: string; time: string }>;
}

/**
 * Botão que leva ao fluxo de agendamento próprio (`/{slug}/agendar`).
 *
 * Ganha tipo próprio — em vez de ser um `link` — porque DERIVA: o destino sai do
 * slug do site, e o bloco só é válido se existir uma `agenda` configurada. É a
 * mesma razão de o `whatsapp` ter tipo próprio e o "Achadinhos" não ter.
 */
export interface BookingBlock extends BlockBase {
  type: 'booking';
  /** Padrão: 'Reserve seu horário'. */
  title?: string;
  /**
   * Preenchido por `resolveBlocks()` a partir do slug. Só escreva aqui para
   * apontar para outro lugar — um agendamento externo, por exemplo.
   */
  href?: string;
  emphasis?: 'primary' | 'default';
}

/** Linha de ícones de redes sociais. */
export interface SocialsBlock extends BlockBase {
  type: 'socials';
  title?: string;
  items: Array<{
    network: SocialNetwork;
    /** Sem '@'. Para whatsapp, o telefone com DDI. */
    handle: string;
    /** Sobrescreve a URL derivada. */
    href?: string;
    /** Esconde só esta rede, mantendo o resto da linha. */
    hidden?: boolean;
  }>;
}

/** Título que separa grupos de blocos. */
export interface SectionBlock extends BlockBase {
  type: 'section';
  title: string;
}

/** Parágrafo curto entre blocos (aviso, recado, condição). */
export interface NoteBlock extends BlockBase {
  type: 'note';
  text: string;
}

export type Block =
  | LinkBlock
  | WhatsappBlock
  | BookingBlock
  | LocationBlock
  | HoursBlock
  | SocialsBlock
  | SectionBlock
  | NoteBlock;

export type BlockType = Block['type'];
