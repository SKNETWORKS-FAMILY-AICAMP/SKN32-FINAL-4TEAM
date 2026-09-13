-- Some pre-0009 installations already have these definitions from older base SQL.
-- Preserve values and reject incompatible definitions rather than silently skipping.
DO $$
DECLARE col record; actual record;
BEGIN
  FOR col IN SELECT * FROM (VALUES
    ('app_user','email_verified_at','timestamp with time zone',false,NULL::text),
    ('app_user','updated_at','timestamp with time zone',true,'now()'),
    ('user_preference','ui_settings','jsonb',true,'''{}''::jsonb')
  ) AS expected(tbl,name,typ,required,default_expr)
  LOOP
    SELECT format_type(a.atttypid,a.atttypmod) AS typ,a.attnotnull AS required,
           pg_get_expr(d.adbin,d.adrelid) AS default_expr INTO actual
    FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
    WHERE a.attrelid=format('identity.%I',col.tbl)::regclass AND a.attname=col.name AND NOT a.attisdropped;
    IF FOUND AND (actual.typ IS DISTINCT FROM col.typ OR actual.required IS DISTINCT FROM col.required
                  OR actual.default_expr IS DISTINCT FROM col.default_expr) THEN
      RAISE EXCEPTION '0009 compatibility: incompatible identity.%.% definition',col.tbl,col.name;
    END IF;
  END LOOP;
END $$;
ALTER TABLE identity.app_user
  ADD COLUMN IF NOT EXISTS email_verified_at timestamptz,
  ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE identity.user_preference
  ADD COLUMN IF NOT EXISTS ui_settings jsonb NOT NULL DEFAULT '{}'::jsonb;
DO $$
DECLARE t record;
BEGIN
  SELECT * INTO t FROM pg_trigger WHERE tgrelid='identity.app_user'::regclass AND tgname='set_updated_at';
  IF FOUND THEN
    IF t.tgfoid <> 'shared.set_updated_at()'::regprocedure OR t.tgtype <> 19
       OR t.tgnargs <> 0 OR t.tgqual IS NOT NULL OR t.tgattr::text <> '' OR t.tgenabled <> 'O' THEN
      RAISE EXCEPTION '0009 compatibility: incompatible identity.app_user.set_updated_at trigger';
    END IF;
  ELSE
    CREATE TRIGGER set_updated_at BEFORE UPDATE ON identity.app_user
      FOR EACH ROW EXECUTE FUNCTION shared.set_updated_at();
  END IF;
END $$;
