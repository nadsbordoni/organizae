import type { IconName, SocialNetwork } from '@/types/blocks';

/** A configuração traz só telefone ou handle; URL, rótulo e ícone saem daqui, NUNCA digitados à mão. */

/** `wa.me` funciona tanto no app quanto no WhatsApp Web. */
export function whatsappUrl(phone: string, message?: string): string {
  const digits = phone.replace(/\D/g, '');
  const base = `https://wa.me/${digits}`;
  const text = message && plainText(message);
  return text ? `${base}?text=${encodeURIComponent(text)}` : base;
}

/**
 * Tira o que impede o envio. Emoji: o WhatsApp não preenche a mensagem (testado em 2026-09-10).
 * Surrogate isolado (emoji cortado ao colar): faz `encodeURIComponent` lançar e trava o botão.
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
    /** Ex: 'Instagram: @joanamanicure'. */
    accessibleLabel: `${meta.label}: ${meta.display(handle)}`,
  };
}

function strip(handle: string): string {
  return handle.replace(/^@/, '').trim();
}

export function isExternal(href: string): boolean {
  return /^(https?:)?\/\//.test(href) || href.startsWith('mailto:') || href.startsWith('tel:');
}

/**
 * A ÚNICA fonte de `target` e `rel`. `sponsored` SÓ em link declarado de afiliado: marcar link comum
 * como pago mente para o buscador; omitir esconde dele uma relação comercial que existe.
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

/** `output=embed` dispensa chave de API; a Embed API oficial exigiria chave e faturamento por cliente. */
export function mapEmbedUrl(query: string): string {
  const params = new URLSearchParams({
    q: query,
    hl: 'pt-BR',
    z: '16',
    output: 'embed',
  });
  return `https://maps.google.com/maps?${params}`;
}
