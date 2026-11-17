import type { Block } from './blocks';
import type { Agenda } from './agenda';
import type { ThemeTokens } from './theme';

/**
 * Um cliente = um arquivo em `src/config/sites/` exportando um `SiteConfig`.
 * DADO puro: sem JSX, sem lógica, sem import de componente.
 */

export interface Profile {
  name: string;
  /** Categoria abaixo do nome, em caixa alta. Ex: 'Studio', 'Barbearia'. */
  nameSuffix?: string;
  /** O diferencial, em UMA linha curta. Ex: 'Especialista em Molde F1'. */
  headline?: string;
  /** Itens curtos. Separado da `headline` de propósito: junto, o diferencial vira mais um item. */
  services?: string[];
  avatar?: {
    src: string;
    alt: string;
  };
}

export interface SiteSeo {
  /** Padrão: nome do perfil. */
  title?: string;
  /** Padrão: composto de `profile.headline` + `profile.services`. */
  description?: string;
  /** 1200x630. Caminho a partir de /public. */
  ogImage?: string;
  favicon?: string;
  /** Use em demo e rascunho. */
  noindex?: boolean;
}

/** Vira a subpágina `/{slug}/{collection.slug}`. */
export interface Collection {
  slug: string;
  /** Sobretítulo em caixa alta acima do título. Ex: 'Cuide-se em casa'. */
  eyebrow?: string;
  title: string;
  intro?: string;
  /**
   * Aviso de publicidade, abaixo dos produtos. PREENCHA se houver link de afiliado: o CONAR
   * exige publicidade identificável, e o build quebra sem ele. Diga que não há custo extra.
   */
  disclosure?: string;
  items: CollectionItem[];
}

export interface CollectionItem {
  name: string;
  /** Selo curto acima do nome. Ex: 'Novidade', 'Mais vendido'. */
  badge?: string;
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
  blocks: Block[];
  /** Presente, gera a rota `/{slug}/agendar` e habilita o bloco `booking`. */
  agenda?: Agenda;
  seo?: SiteSeo;
  collections?: Collection[];
  /** Aviso de publicidade da página principal. Ver `Collection.disclosure`. */
  disclosure?: string;
  /** Padrão: nome do perfil e o ano. */
  footerNote?: string;
}
