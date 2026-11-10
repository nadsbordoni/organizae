/**
 * Página = lista ordenada de blocos. Tipo novo: interface aqui, união `Block`, componente em
 * `src/blocks/` e REGISTRY de `blocks/BlockList.astro` (esquecer quebra o build, não a produção).
 * Antes, veja se um `link` com outras props resolve: só ganha tipo quem tem ESTRUTURA diferente.
 */

/** Ver `src/components/Icon.astro`. */
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
  | 'users'
  | 'briefcase'
  | 'wallet'
  | 'chart'
  | 'settings'
  | 'search'
  | 'bell'
  | 'download'
  | 'plus'
  | 'home'
  | 'check-circle'
  | 'alert-circle'
  | 'info'
  | 'more'
  | 'eye'
  | 'eye-off'
  | 'logout'
  | 'instagram'
  | 'tiktok'
  | 'facebook'
  | 'youtube';

/** A URL e o rótulo são derivados do handle. */
export type SocialNetwork =
  | 'instagram'
  | 'tiktok'
  | 'facebook'
  | 'youtube'
  | 'whatsapp';

interface BlockBase {
  subtitle?: string;
  /** Esconde o bloco sem apagar a configuração. */
  hidden?: boolean;
}

export interface LinkBlock extends BlockBase {
  type: 'link';
  title: string;
  icon?: IconName;
  /** Miniatura à esquerda. Substitui o ícone quando presente. */
  image?: { src: string; alt: string };
  href: string;
  /** Use `primary` em NO MÁXIMO um ou dois blocos: se tudo é destaque, nada é. */
  emphasis?: 'primary' | 'default';
  /** Força nova aba. Por padrão, link externo já abre em nova aba. */
  external?: boolean;
  /**
   * Link que dá comissão. Marca o `rel` como `sponsored` e OBRIGA a página a ter
   * `disclosure`, senão o build quebra. Ver `lib/disclosure.ts`.
   */
  affiliate?: boolean;
}

export interface WhatsappBlock extends BlockBase {
  type: 'whatsapp';
  title: string;
  /** Só dígitos, com DDI e DDD. Ex: '5511999998888'. */
  phone: string;
  /** Emoji é removido: com ele, o WhatsApp não preenche a mensagem. Ver `whatsappUrl()`. */
  message?: string;
  emphasis?: 'primary' | 'default';
}

export interface LocationBlock extends BlockBase {
  type: 'location';
  title: string;
  /** Uma linha por item. */
  address: string[];
  mapsUrl: string;
  /**
   * `true` deriva a busca do `address`; uma string usa o `src` de "Compartilhar → Incorporar
   * um mapa" do Google, mais preciso. CUSTA CARO: ~1 MB e JS de terceiro ao rolar até ele.
   */
  map?: boolean | string;
  /** Busca de `map: true` no lugar do `address`. Aceita "lat,long". */
  mapQuery?: string;
}

/** Bloco próprio, e não campo da localização: há negócio com horário e sem endereço fixo. */
export interface HoursBlock extends BlockBase {
  type: 'hours';
  /** Padrão: 'Horário de atendimento'. */
  title?: string;
  /**
   * Ex: `{ days: 'Ter a Sex', time: '08:00 às 19:30' }`. OMITA se houver `agenda`: o
   * `resolveBlocks()` deriva dela. Preencher SOBRESCREVE; use só quando o horário de porta
   * aberta diferir do de hora marcada.
   */
  schedule?: Array<{ days: string; time: string }>;
}

/** Leva a `/{slug}/agendar`. Não é `link` porque DERIVA do slug e exige `agenda` configurada. */
export interface BookingBlock extends BlockBase {
  type: 'booking';
  /** Padrão: 'Reserve seu horário'. */
  title?: string;
  /** Derivado do slug por `resolveBlocks()`. Preencha só para um agendamento externo. */
  href?: string;
  emphasis?: 'primary' | 'default';
}

export interface SocialsBlock extends BlockBase {
  type: 'socials';
  title?: string;
  items: Array<{
    network: SocialNetwork;
    /** Sem '@'. Para whatsapp, o telefone com DDI. */
    handle: string;
    /** Sobrescreve a URL derivada. */
    href?: string;
    hidden?: boolean;
  }>;
}

export interface SectionBlock extends BlockBase {
  type: 'section';
  title: string;
}

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
