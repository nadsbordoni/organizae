import type { ThemeTokens } from '@/types/theme';

/**
 * Tokens do tema → CSS custom properties, aplicadas no elemento raiz.
 * `color.brand` vira `--site-color-brand`. Trocar de tema não custa JavaScript
 * em runtime, só valores diferentes num atributo `style` gerado no build.
 */
export function toCssVars(theme: ThemeTokens): string {
  const declarations: string[] = [];

  for (const [group, tokens] of Object.entries(theme)) {
    for (const [name, value] of Object.entries(tokens as Record<string, string>)) {
      declarations.push(`--site-${group}-${kebab(name)}: ${value};`);
    }
  }

  return declarations.join(' ');
}

function kebab(value: string): string {
  return value.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`);
}
