import type { Block } from './blocks';
import type { Agenda } from './agenda';
import type { ThemeTokens } from './theme';

/**
 * Configuração de um site.
 *
 * Um cliente = um arquivo em `src/config/sites/` exportando um `SiteConfig`.
 * Isto é DADO puro: sem JSX, sem lógica, sem import de componente.
 */

export interface Profile {
  name: string;
  /** Categoria abaixo do nome, em caixa alta. Ex: 'Studio', 'Barbearia'. */
  nameSuffix?: string;
  /**
   * O diferencial, em UMA linha curta. Ex: 'Especialista em Molde F1'.
   * Se virar parágrafo, deixa de ser destaque.
   */
  headline?: string;
  /**
   * O catálogo, em itens curtos. Separado da `headline` de propósito: juntos,
   * o diferencial vira só mais um item da lista.
   */
  services?: string[];
  avatar?: {
    src: string;
    /** Descrição para leitores de tela. */
    alt: string;
  };
}

export interface SiteSeo {
  /** Padrão: nome do perfil. */
  title?: string;
  /** Padrão: composto de `profile.headline` + `profile.services`. */
  description?: string;
  /** Imagem do preview, 1200x630. Caminho a partir de /public. */
  ogImage?: string;
  favicon?: string;
  /** Esconde dos buscadores. Use em demo e rascunho. */
  noindex?: boolean;
}

/** Coleção de produtos — vira a subpágina `/{slug}/{collection.slug}`. */
export interface Collection {
  slug: string;
  title: string;
  intro?: string;
  /**
   * Aviso de publicidade, abaixo dos produtos. PREENCHA sempre que houver link
   * de afiliado: o CONAR exige que a publicidade seja identificável, e o build
   * quebra sem ele. Diga que não há custo extra — é a dúvida de quem leu
   * "comissão".
   */
  disclosure?: string;
  items: CollectionItem[];
}

export interface CollectionItem {
  name: string;
  description?: string;
  /** Texto livre. Ex: 'R$ 89,90' ou 'a partir de R$ 40'. */
  price?: string;
  image?: { src: string; alt: string };
  /** Sem ele, o item aparece sem botão. */
  href?: string;
  /** Padrão: 'Ver produto'. */
  ctaLabel?: string;
  /** Link que dá comissão. Ver `disclosure` acima. */
  affiliate?: boolean;
}

export interface SiteConfig {
  /** Segmento da URL, em kebab-case. */
  slug: string;
  /** Crie com `defineTheme()` em `src/themes/`. */
  theme: ThemeTokens;
  profile: Profile;
  /** Ordem do array = ordem na tela. */
  blocks: Block[];
  /**
   * Expediente e catálogo de serviços. Presente, gera a rota `/{slug}/agendar` e
   * habilita o bloco `booking`. Ausente, o site é só uma página de links.
   */
  agenda?: Agenda;
  seo?: SiteSeo;
  collections?: Collection[];
  /** Aviso de publicidade da página principal. Ver `Collection.disclosure`. */
  disclosure?: string;
  /** Padrão: nome do perfil e o ano. */
  footerNote?: string;
}
