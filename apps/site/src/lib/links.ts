import type { IconName, SocialNetwork } from '@/types/blocks';

/**
 * Quem edita a configuração escreve o mínimo (um telefone, um handle) e estas
 * funções montam URL, rótulo e ícone — evitando URL digitada à mão, que é a
 * causa mais comum de link quebrado.
 */

/**
 * Monta a URL do WhatsApp com a mensagem já preenchida.
 * `wa.me` funciona tanto no app quanto no WhatsApp Web.
 */
export function whatsappUrl(phone: string, message?: string): string {
  const digits = phone.replace(/\D/g, '');
  const base = `https://wa.me/${digits}`;
  const text = message && plainText(message);
  return text ? `${base}?text=${encodeURIComponent(text)}` : base;
}

/**
 * Tira da mensagem o que impede o envio.
 *
 * Emoji: testado em 2026-09-10 com 💕, o WhatsApp não preencheu a mensagem.
 * Surrogate isolado (texto colado cortado no meio de um emoji): faz o
 * `encodeURIComponent` lançar, e o botão de enviar para de responder.
 */
function plainText(text: string): string {
  return text
    .replace(/\p{Cs}/gu, '')
    .replace(/[\p{Extended_Pictographic}\p{Emoji_Modifier}\p{Regional_Indicator}\u200D\uFE0F\u20E3]/gu, '')
    .replace(/[ \t]{2,}/g, ' ');
}

interface SocialMeta {
  label: string;
  icon: IconName;
  /** Como o handle aparece na tela / em leitores de tela. */
  display: (handle: string) => string;
  url: (handle: string) => string;
}

const SOCIAL: Record<SocialNetwork, SocialMeta> = {
  instagram: {
    label: 'Instagram',
    icon: 'instagram',
    display: (h) => `@${strip(h)}`,
    url: (h) => `https://instagram.com/${strip(h)}`,
  },
  tiktok: {
    label: 'TikTok',
    icon: 'tiktok',
    display: (h) => `@${strip(h)}`,
    url: (h) => `https://tiktok.com/@${strip(h)}`,
  },
  facebook: {
    label: 'Facebook',
    icon: 'facebook',
    display: (h) => strip(h),
    url: (h) => `https://facebook.com/${strip(h)}`,
  },
  youtube: {
    label: 'YouTube',
    icon: 'youtube',
    display: (h) => `@${strip(h)}`,
    url: (h) => `https://youtube.com/@${strip(h)}`,
  },
  whatsapp: {
    label: 'WhatsApp',
    icon: 'whatsapp',
    display: (h) => h,
    url: (h) => whatsappUrl(h),
  },
};

/** Resolve rede + handle em URL, ícone e rótulo acessível. */
export function resolveSocial(
  network: SocialNetwork,
  handle: string,
  override?: string,
) {
  const meta = SOCIAL[network];
  return {
    href: override ?? meta.url(handle),
    icon: meta.icon,
    label: meta.label,
    /** Ex: 'Instagram: @joanamanicure' — o que o leitor de tela anuncia. */
    accessibleLabel: `${meta.label}: ${meta.display(handle)}`,
  };
}

function strip(handle: string): string {
  return handle.replace(/^@/, '').trim();
}

/** `true` se o link sai do site — usado para decidir `target` e `rel`. */
export function isExternal(href: string): boolean {
  return /^(https?:)?\/\//.test(href) || href.startsWith('mailto:') || href.startsWith('tel:');
}

/**
 * `target` e `rel` de um link — a ÚNICA fonte desses atributos.
 *
 * `sponsored` entra só quando o link é declarado de afiliado. Marcar link
 * comum como pago mente para o buscador; deixar link pago sem a marca
 * esconde dele uma relação comercial que existe.
 */
export function linkAttrs({
  href,
  external,
  affiliate,
}: {
  href: string;
  external?: boolean;
  affiliate?: boolean;
}): { target?: '_blank'; rel?: string } {
  if (!(external ?? isExternal(href))) return {};

  const rel = ['noopener', 'noreferrer'];
  if (affiliate) rel.push('sponsored');
  return { target: '_blank', rel: rel.join(' ') };
}

/**
 * URL do mapa do Google para embutir em iframe.
 *
 * Usa o modo `output=embed`, que funciona sem chave de API — a Embed API
 * oficial exigiria uma chave e faturamento configurado, o que seria uma
 * barreira para cada novo cliente da plataforma.
 */
export function mapEmbedUrl(query: string): string {
  const params = new URLSearchParams({
    q: query,
    hl: 'pt-BR',
    z: '16',
    output: 'embed',
  });
  return `https://maps.google.com/maps?${params}`;
}
