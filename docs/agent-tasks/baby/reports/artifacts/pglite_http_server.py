import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from psycopg_pool import ConnectionPool
import src.db
# PGlite transport supports only the constrained, single-connection rehearsal here.
# This changes the test launcher only, not production pool implementation.
src.db._pool=ConnectionPool(src.db.DATABASE_URL,min_size=1,max_size=1,kwargs={'prepare_threshold':None},open=True)
import runpy
runpy.run_path("db/seed.py")["main"]()
runpy.run_path("db/seed_catalog.py")["main"]()
import uvicorn
uvicorn.run('src.api:app',host='127.0.0.1',port=18000)
