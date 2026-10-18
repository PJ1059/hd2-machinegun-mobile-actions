import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.dirname(fileURLToPath(import.meta.url));
const port = Number(process.env.PORT || 5177);
const types = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8',
  '.glb': 'model/gltf-binary', '.gltf': 'model/gltf+json', '.bin': 'application/octet-stream',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp',
  '.svg': 'image/svg+xml', '.ico': 'image/x-icon', '.txt': 'text/plain; charset=utf-8',
};

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, 'http://127.0.0.1');
    let requested = decodeURIComponent(url.pathname);
    if (requested === '/') requested = '/index.html';
    const target = path.resolve(root, `.${requested}`);
    if (!target.startsWith(root + path.sep)) {
      res.writeHead(403); res.end('Forbidden'); return;
    }
    const info = await stat(target);
    if (!info.isFile()) throw Object.assign(new Error('Not found'), { code: 'ENOENT' });
    const content = await readFile(target);
    res.writeHead(200, {
      'Content-Type': types[path.extname(target).toLowerCase()] || 'application/octet-stream',
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
    });
    if (req.method === 'HEAD') res.end(); else res.end(content);
  } catch (error) {
    res.writeHead(error.code === 'ENOENT' ? 404 : 500, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end(error.code === 'ENOENT' ? 'File not found' : 'Unable to read file');
  }
});

server.listen(port, '127.0.0.1', () => {
  console.log(`MG-43 动作预览：http://127.0.0.1:${port}`);
  console.log('停止预览：在此终端按 Ctrl+C。');
});
server.on('error', (error) => {
  console.error(error.code === 'EADDRINUSE' ? `端口 ${port} 已占用。可用 $env:PORT=5178 后重新运行 npm start。` : error.message);
  process.exitCode = 1;
});
