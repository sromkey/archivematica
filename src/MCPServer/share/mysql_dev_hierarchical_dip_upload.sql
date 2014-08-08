
-- New LevelOfDescription table will be created by syncdb automatically, since it is a new table
-- Update SIPArrange table, since syncdb will not modify an existing table
ALTER TABLE main_siparrange ADD sip_id varchar(36) COLLATE utf8_unicode_ci DEFAULT NULL AFTER transfer_uuid, ADD level_of_description varchar(2014) COLLATE utf8_unicode_ci NOT NULL AFTER sip_id;
ALTER TABLE main_siparrange ADD FOREIGN KEY (sip_id) REFERENCES SIPs(sipUUID);
