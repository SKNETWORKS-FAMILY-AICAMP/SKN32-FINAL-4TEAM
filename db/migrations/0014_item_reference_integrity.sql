-- Validate existing rows too; invalid data must be corrected explicitly, never discarded.
ALTER TABLE catalog.offer ADD CONSTRAINT offer_id_variant_unique UNIQUE (id, variant_id);
ALTER TABLE catalog.offer_observation ADD CONSTRAINT observation_id_offer_unique UNIQUE (id, offer_id);
ALTER TABLE planning.item
  ADD CONSTRAINT item_id_revision_unique UNIQUE (id, revision_id),
  ADD CONSTRAINT item_revision_fk FOREIGN KEY (revision_id) REFERENCES planning.plan_revision(id),
  ADD CONSTRAINT item_variant_fk FOREIGN KEY (variant_id) REFERENCES catalog.product_variant(id),
  ADD CONSTRAINT item_offer_requires_variant CHECK (offer_id IS NULL OR variant_id IS NOT NULL),
  ADD CONSTRAINT item_observation_requires_offer CHECK (offer_observation_id IS NULL OR offer_id IS NOT NULL),
  ADD CONSTRAINT item_offer_variant_fk FOREIGN KEY (offer_id, variant_id) REFERENCES catalog.offer(id, variant_id),
  ADD CONSTRAINT item_observation_offer_fk FOREIGN KEY (offer_observation_id, offer_id) REFERENCES catalog.offer_observation(id, offer_id);
ALTER TABLE planning.requirement
  ADD CONSTRAINT requirement_fulfilled_item_revision_fk
  FOREIGN KEY (fulfilled_by_item_id, revision_id) REFERENCES planning.item(id, revision_id);
