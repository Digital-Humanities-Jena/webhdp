# Account access, usage and limits

Open **Account → Usage and limits** to see your upload storage, work in progress and limits. The page reports your account's usage. Open **HPC access and allocations** to view your own compute requests, cancel a queued request or release an idle allocation.

## Workspaces and publishing

- Personal sessions are private by default. Shared session access depends on your assigned role and the session's sharing settings.
- Affiliation is displayed on your profile. To join an existing workspace,
  accept an invitation with your verified account. You can also request a
  new workspace for site approval. [Institution workspaces and invitations](../workflows/institutions-credentials-governance.md)
- A publishing run uses an authorized credential for the selected environment. An authorized institution credential or explicitly shared credential can be used where its settings permit.
- Access to server-mounted inputs requires a separate grant. You can still upload files to your own session on a local-mode installation.
- A verified user can request HPC access. A pre-reserved GPU additionally requires a grant for that reservation. The sign-in account that claims it controls that claim.

## How requests count

| Work | Account allowance | How to free capacity |
| --- | --- | --- |
| Source uploads | 50 GiB of stored and reserved sources, three concurrent uploads, and 50 GiB of streamed transfers per rolling 24 hours by default | Remove source data you no longer need through the session's authorized controls. Pending uploads count while WebHDP holds their reservations. |
| Pipelines and Playground | Three queued or running executions combined by default | Wait for a run to finish or cancel a queued run from its progress view. |
| 3D tutorial and Sandbox | Three queued or running requests, ten accepted in a rolling 24-hour period, and 256 MiB of model workspace per account | Finished results expire after 48 hours. Check the usage page for the account's current queue and storage allowance. |
| HPC | Separate limits for active allocations and requests waiting in the WebHDP queue, plus a maximum size and duration per new allocation | Cancel a waiting request or release an idle allocation. A job waiting in the cluster scheduler already uses an active WebHDP allocation slot. |
| Connected applications | Each application has an overall queue and storage allowance and can set limits per account. Available workers prioritize eligible accounts with fewer running jobs. Jobs with equal priority are taken in arrival order. | Cancel a queued job or remove uploads when the app provides these controls. |

The source allowance measures files and reservations recorded by WebHDP. Generated results, provider storage restrictions, compute runtime limits and physical disk capacity have separate limits.

## Deployment settings

- Apply the account quota database migration before starting the updated backend and workers. They use the same instance directory and database.
- `ACCOUNT_UPLOAD_STORAGE_BYTES`, `ACCOUNT_UPLOAD_MAX_ACTIVE`, and `ACCOUNT_UPLOAD_STREAM_DAILY_BYTES` set ordinary upload limits. `MAX_CONTENT_LENGTH` controls the maximum HTTP request size.
- `WEBHDP_NATIVE_PROCESSING_ACTIVE_LIMIT` sets the combined active native pipeline and Playground limit. Requests are charged to the initiating account, including work started in an authorized shared session.
- HPC settings define active allocations, queue size, maximum GPUs, duration, and how long an unstarted request can wait. See [HPC access and storage](../workflows/hpc-cloud-storage.md).
- WebHDP-Link allows a maximum of five queued jobs per account by default, bounded by the application's queue limit. The default account storage share is half the application quota or one maximum upload, whichever is larger, bounded by the app quota. Apps with a single queue slot retain their full app allowance per account. An administrator can adjust both account limits in [WebHDP-Link settings](webhdp_link.md).
