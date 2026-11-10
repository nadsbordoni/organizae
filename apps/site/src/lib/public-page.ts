import { getSecret } from 'astro:env/server';
import { whatsappUrl } from './links';
import { baseTheme } from '@/themes/base';
import type { Block } from '@/types/blocks';
import type { SiteConfig } from '@/types/site';

/**
 * Página publicada no painel e servida pela API (`GET /api/v1/public/pages/{slug}`).
 * Os estúdios de `src/config/sites/` continuam funcionando; a API só entra quando o slug não está lá.
 */

export interface PublicPageService {
  id: string;
  name: string;
  description: string | null;
  /** Decimal em texto, como o Pydantic serializa. Ex: "120.00". */
  price: string;
  duration_minutes: number;
}

export interface PublicPage {
  id: string;
  slug: string;
  name: string;
  logo_url: string | null;
  description: string | null;
  /** Como foi digitado no cadastro: pode vir sem DDI. */
  whatsapp: string;
  /** Sem '@'. */
  instagram: string | null;
  address: string | null;
  service_mode: 'PRESENCIAL' | 'ONLINE' | 'HIBRIDO';
  services: PublicPageService[];
}

/** Mesma regra do slug na API: evita chamar a API com qualquer coisa digitada na URL. */
const SLUG_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*$/;

const DEFAULT_API_URL = 'http://localhost:8000';

export function apiBaseUrl(): string {
  // Lido ao atender o pedido, não no build: trocar a API não exige gerar o site de novo.
  const url = getSecret('ORGANIZAE_API_URL') ?? DEFAULT_API_URL;
  return url.replace(/\/+$/, '');
}

/** `null` quando a página não existe ou ainda não foi publicada. */
export async function fetchPublicPage(
  slug: string,
  apiUrl: string = apiBaseUrl(),
): Promise<PublicPage | null> {
  if (slug.length > 80 || !SLUG_PATTERN.test(slug)) return null;

  const response = await fetch(`${apiUrl}/api/v1/public/pages/${slug}`, {
    headers: { Accept: 'application/json' },
  });
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(`A API respondeu ${response.status} ao buscar a página "${slug}".`);
  }
  return (await response.json()) as PublicPage;
}

/** Monta a mesma página de links dos estúdios configurados, com os dados da API. */
export function toSiteConfig(page: PublicPage): SiteConfig {
  const phone = withCountryCode(page.whatsapp);

  const blocks: Block[] = [
    {
      type: 'booking',
      title: 'Agendar um horário',
      // Agendamento online para páginas da API é outra história; até lá, o pedido sai pelo WhatsApp.
      href: whatsappUrl(phone, `Olá, ${page.name}! Quero agendar um horário.`),
      emphasis: 'primary',
    },
  ];

  if (page.services.length > 0) {
    blocks.push(
      { type: 'section', title: 'Nossos serviços' },
      ...page.services.map(
        (service): Block => ({
          type: 'link',
          title: service.name,
          subtitle: serviceDetails(service),
          icon: 'sparkles',
          href: whatsappUrl(phone, `Olá, ${page.name}! Quero agendar ${service.name}.`),
        }),
      ),
    );
  }

  blocks.push(
    { type: 'section', title: 'Contato' },
    {
      type: 'whatsapp',
      title: 'Conversar no WhatsApp',
      subtitle: 'Tire suas dúvidas ou peça ajuda para escolher',
      phone,
      message: `Olá, ${page.name}! Queria tirar uma dúvida.`,
    },
  );

  if (page.instagram) {
    blocks.push({ type: 'socials', items: [{ network: 'instagram', handle: page.instagram }] });
  }

  if (page.address) {
    blocks.push({
      type: 'location',
      title: 'Como chegar',
      address: [page.address],
      mapsUrl: `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(page.address)}`,
    });
  }

  return {
    slug: page.slug,
    theme: baseTheme,
    profile: {
      name: page.name,
      headline: page.description ?? undefined,
      avatar: page.logo_url ? { src: page.logo_url, alt: `Logo de ${page.name}` } : undefined,
    },
    seo: {
      title: page.name,
      description: page.description ?? `Serviços e agendamento de ${page.name}.`,
    },
    blocks,
  };
}

/** "60 min • R$ 120,00" */
export function serviceDetails(service: PublicPageService): string {
  const price = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(
    Number(service.price),
  );
  return `${service.duration_minutes} min • ${price}`;
}

/** O cadastro aceita "11 98888-2018"; o `wa.me` exige DDI. Sem DDI, assume Brasil. */
export function withCountryCode(phone: string): string {
  const digits = phone.replace(/\D/g, '');
  return digits.startsWith('55') && digits.length >= 12 ? digits : `55${digits}`;
}
