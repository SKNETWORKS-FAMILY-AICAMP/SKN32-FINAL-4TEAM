// Ephemeral PostgreSQL WASM + pgvector, loopback only. No existing DB is touched.
import { PGlite } from '@electric-sql/pglite';
import { PGLiteSocketServer } from '@electric-sql/pglite-socket';
import { vector } from '@electric-sql/pglite-pgvector';

const db = await PGlite.create({ extensions: { vector } });
const server = new PGLiteSocketServer({ db, host: '127.0.0.1', port: 55432 });
await server.start();
console.log('RAG test PostgreSQL ready at 127.0.0.1:55432 (ephemeral)');
async function stop() { await server.stop(); await db.close(); process.exit(0); }
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
