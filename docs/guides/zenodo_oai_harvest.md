# Zenodo OAI Harvest

Zenodo OAI Harvest retrieves public Zenodo metadata through OAI-PMH and stores it as explorer-only `.hdpc` shard collections.

Use this workflow when WebHDP needs public community or repository metadata without a Zenodo API key. It is separate from Zenodo Account Deep Retrieval, which remains the authenticated workflow for account inventories, drafts, and edit/version capability checks.

## Where To Find It

Open:

```text
Tools -> Zenodo OAI Harvest
```

The default target is:

```text
set = user-3dbigdataspace
metadataPrefix = oai_datacite
baseURL = https://zenodo.org/oai2d
```

The shorthand UI value `3dbigdataspace` is normalized to the Zenodo OAI set `user-3dbigdataspace`.

## What It Retrieves

The workflow harvests public OAI-PMH records with `ListRecords`.

Supported metadata prefixes are:

- `oai_datacite` as the default rich metadata format
- `dcat` for public distribution/file-link discovery where Zenodo exposes it
- `oai_dc` for lightweight Dublin Core interoperability checks

OAI Harvest does not retrieve drafts, private records, restricted owner views, edit links, or unpublished deposition state.

## Storage Model

Harvest output uses the same durable shard style as account retrieval:

- generated sessions use `origin_type="zenodo_oai_harvest"`
- generated sessions use `access_mode="explorer_only"`
- records use `zenodo_records.record_origin="zenodo_oai_harvest"`
- snapshots use `zenodo_record_snapshots.snapshot_stage="oai_pmh_record"`
- raw OAI XML is preserved in the record snapshot payload

No separate database schema migration is required.

## Incremental Harvests

After a successful full harvest, an incremental harvest can use the latest harvested OAI datestamp and subtract an overlap window. The default overlap is `24` hours.

Zenodo's OAI endpoint reports that deleted records are not tracked through OAI-PMH, so this workflow does not claim deletion detection. Use future Zenodo metadata-dump reconciliation for deletion-aware audits.

## Operations

The job can be preflighted, queued, paused, resumed, cancelled, deleted, searched, exported, compacted, and scheduled from the Tools page.

For the `3dbigdataspace` community, expect a large full harvest to produce many page-level shards before compaction because Zenodo OAI-PMH pages are small. Use a bounded `max_records` value such as `100` for first live verification.

## Related Workflows

- [Zenodo Account Deep Retrieval](zenodo_account_retrieval.md): authenticated account inventory, drafts, all versions, and edit/version capability inference.
- [Zenodo API Keys](zenodo_api_keys.md): required for publication and authenticated retrieval, not required for OAI Harvest.
