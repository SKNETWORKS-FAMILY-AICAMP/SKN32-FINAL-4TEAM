"""0009 bootstrap compatibility; isolated databases, never application tables."""
import os
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest

DSN = os.getenv('RAG_TEST_DATABASE_URL')
pytestmark = pytest.mark.skipif(not DSN, reason='requires disposable PostgreSQL')
PATCH = Path(__file__).resolve().parents[1] / 'db/compatibility/0009_existing_identity_fields.sql'

@pytest.fixture
def legacy():
    params = conninfo_to_dict(DSN)
    name = 'migration9_' + uuid4().hex[:12]
    with psycopg.connect(make_conninfo(**{**params,'dbname':'postgres'}),autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        try:
            with psycopg.connect(make_conninfo(**{**params,'dbname':name})) as c:
                c.execute('CREATE SCHEMA identity; CREATE SCHEMA shared; CREATE TABLE identity.app_user(id integer PRIMARY KEY); CREATE TABLE identity.user_preference(user_id integer PRIMARY KEY)')
                c.execute('CREATE FUNCTION shared.set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.updated_at=now(); RETURN NEW; END $$')
                c.commit()
                yield c
        finally:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


def test_add_missing_and_reuse_exact_definitions_preserving_values(legacy):
    patch = PATCH.read_text()
    legacy.execute(patch)
    legacy.execute("INSERT INTO identity.app_user(id,email_verified_at) VALUES (1,'2025-01-01Z')")
    legacy.execute('INSERT INTO identity.user_preference(user_id,ui_settings) VALUES (1,\'{"theme":"dark"}\')')
    before = legacy.execute('SELECT * FROM identity.app_user').fetchall()
    legacy.execute(patch)
    assert legacy.execute('SELECT * FROM identity.app_user').fetchall() == before
    assert legacy.execute('SELECT ui_settings FROM identity.user_preference').fetchone()[0] == {'theme':'dark'}
    assert legacy.execute("SELECT count(*) FROM pg_trigger WHERE tgrelid='identity.app_user'::regclass AND NOT tgisinternal").fetchone()[0] == 1


def test_partial_existing_fields_are_completed(legacy):
    legacy.execute('ALTER TABLE identity.app_user ADD COLUMN email_verified_at timestamptz')
    legacy.execute(PATCH.read_text())
    assert legacy.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema='identity' AND column_name IN ('updated_at','ui_settings')").fetchone()[0] == 2


def test_incompatible_existing_field_is_rejected_atomically(legacy):
    legacy.execute('ALTER TABLE identity.app_user ADD COLUMN email_verified_at text')
    with pytest.raises(psycopg.errors.RaiseException,match='incompatible identity.app_user.email_verified_at'), legacy.transaction():
        legacy.execute(PATCH.read_text())
    assert legacy.execute("SELECT data_type FROM information_schema.columns WHERE table_schema='identity' AND column_name='email_verified_at'").fetchone()[0] == 'text'


def test_incompatible_trigger_is_rejected(legacy):
    legacy.execute(PATCH.read_text())
    legacy.execute('ALTER TABLE identity.app_user DISABLE TRIGGER set_updated_at')
    with pytest.raises(psycopg.errors.RaiseException,match='incompatible.*trigger'), legacy.transaction():
        legacy.execute(PATCH.read_text())
