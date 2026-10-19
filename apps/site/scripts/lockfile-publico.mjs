/**
 * Garante que o package-lock.json aponte para o registro público do npm.
 *
 * POR QUE ISSO EXISTE: quando o npm está configurado para um espelho privado
 * (comum em rede corporativa), `npm install` grava no lockfile a URL do
 * espelho, não a pública. Aí o build em CI externo falha com `ENOTFOUND`,
 * porque aquele host não existe fora daquela rede — e o erro não menciona
 * lockfile nenhum, o que torna o diagnóstico demorado.
 *
 * Rode depois de QUALQUER mudança de dependência: `npm run lockfile:publico`
 *
 * Com `--check` não escreve nada, só falha se achar URL fora do registro
 * público. É assim que o `npm run build` avisa antes do push — o próximo
 * `npm install` reintroduz o problema silenciosamente.
 *
 * Os `integrity` não mudam: é o mesmo tarball, servido de outro endereço. Se
 * algum não bater, o `npm ci` falha na verificação — alto e claro, não calado.
 */
import { readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const LOCKFILE = fileURLToPath(new URL('../package-lock.json', import.meta.url));
const PUBLICO = 'https://registry.npmjs.org';
const HOST_PUBLICO = 'registry.npmjs.org';
const SOMENTE_CHECAR = process.argv.includes('--check');

const lock = JSON.parse(await readFile(LOCKFILE, 'utf8'));
const forasteiros = [];

for (const [caminho, pacote] of Object.entries(lock.packages ?? {})) {
  const { resolved, version } = pacote;
  // Só tarball do registro: dependência de git, `file:` ou link fica de fora.
  if (!resolved?.startsWith('https://') || !resolved.endsWith('.tgz')) continue;
  if (new URL(resolved).host === HOST_PUBLICO) continue;

  // O nome vem do último segmento `node_modules/` da chave, e não da URL do
  // espelho — cada espelho prefixa o caminho de um jeito diferente.
  const nome = caminho.split('node_modules/').pop();
  if (!nome || !version) {
    forasteiros.push({ caminho, resolved, corrigivel: false });
    continue;
  }

  // Em pacote com escopo, o arquivo não repete o escopo:
  // @astrojs/check -> @astrojs/check/-/check-0.9.10.tgz
  const arquivo = `${nome.split('/').pop()}-${version}.tgz`;
  forasteiros.push({ caminho, resolved, url: `${PUBLICO}/${nome}/-/${arquivo}` });
}

if (forasteiros.length === 0) {
  if (!SOMENTE_CHECAR) console.log('Nada a trocar: o lockfile já é público.');
  process.exit(0);
}

const hosts = [...new Set(forasteiros.map((f) => new URL(f.resolved).host))];

if (SOMENTE_CHECAR) {
  console.error(
    `\npackage-lock.json tem ${forasteiros.length} URL(s) fora do registro público.\n` +
      `Hosts encontrados: ${hosts.join(', ')}\n` +
      'CI externo não resolve esses endereços e o deploy falha.\n' +
      'Corrija com: npm run lockfile:publico',
  );
  process.exit(1);
}

const naoCorrigiveis = forasteiros.filter((f) => !f.url);
if (naoCorrigiveis.length > 0) {
  console.error('Não consegui derivar a URL pública de:');
  for (const f of naoCorrigiveis) console.error(`  ${f.caminho}`);
  process.exit(1);
}

let conteudo = await readFile(LOCKFILE, 'utf8');
for (const { resolved, url } of forasteiros) {
  conteudo = conteudo.replaceAll(`"${resolved}"`, `"${url}"`);
}

JSON.parse(conteudo);
await writeFile(LOCKFILE, conteudo);

console.log(`${forasteiros.length} URL(s) reescrita(s), de: ${hosts.join(', ')}`);
