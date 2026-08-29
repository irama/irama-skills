/* A static server for the fixture decks, on Node's standard library alone.

   The fixtures need a real http origin, not file://, because the runtime keeps
   the whole review in localStorage and a file:// page has an opaque origin that
   cannot write to it.

   `/deck-comments.js` is served straight out of ../assets, so the suite always
   drives the shipped asset and never a copy of it that can drift. */
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = fileURLToPath(new URL('.', import.meta.url));
const FIXTURES = join(HERE, 'fixtures');
const ASSET = join(HERE, '..', 'assets', 'deck-comments.js');
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css',
                '.json': 'application/json' };

export const PORT = Number(process.env.DECK_TEST_PORT || 4319);

createServer(async (req, res) => {
  const path = normalize(decodeURIComponent(req.url.split('?')[0]));
  const file = path.endsWith('/deck-comments.js')
    ? ASSET
    : join(FIXTURES, path.replace(/^(\.\.[/\\])+/, ''));
  try {
    const body = await readFile(file);
    res.writeHead(200, { 'content-type': TYPES[extname(file)] || 'application/octet-stream',
                         'cache-control': 'no-store' });
    res.end(body);
  } catch {
    res.writeHead(404, { 'content-type': 'text/plain' });
    res.end('not found');
  }
}).listen(PORT, () => console.log(`fixtures on http://127.0.0.1:${PORT}`));
