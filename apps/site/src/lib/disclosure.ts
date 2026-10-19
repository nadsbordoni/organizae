/**
 * Link com `affiliate: true` obriga a página a ter `disclosure`. Quem esquece
 * descobre no BUILD, não em produção.
 */

/** Considera só item visível. */
export function hasAffiliate(
  items: ReadonlyArray<{ affiliate?: boolean; hidden?: boolean }>,
): boolean {
  return items.some((item) => item.affiliate === true && !item.hidden);
}

/** `where` entra na mensagem, para localizar a configuração culpada. */
export function assertDisclosure(
  items: ReadonlyArray<{ affiliate?: boolean; hidden?: boolean }>,
  disclosure: string | undefined,
  where: string,
): void {
  if (hasAffiliate(items) && !disclosure?.trim()) {
    throw new Error(
      `${where}: há link com \`affiliate: true\` e nenhum \`disclosure\`. ` +
        'O CONAR exige aviso visível de publicidade — preencha `disclosure` na configuração.',
    );
  }
}
