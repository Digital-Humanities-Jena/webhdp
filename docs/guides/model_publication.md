# Prepare a 3D model for Zenodo Sandbox

[Prepare a 3D model](https://hdp.3drepo.eu/model-publication) packages one model using a CPU worker, checks its texture references, maps its metadata and creates a Zenodo Sandbox draft. The results are available during the run, with a confirmed file inventory when Sandbox finishes receiving them. The workflow is also available from the Uploads area.

## Try a model

The [sample library](https://hdp.3drepo.eu/model-publication/samples) is public. The ZIP files include original CC0 models and a Metadata Source File (MSF).

| Model | Package | What to look for |
| --- | --- | --- |
| Terracotta Vessel | Nested OBJ, MTL and texture folders | The existing references and folder structure carry through into the prepared ZIP. |
| Painted Floor Tile | glTF with separate geometry and image folders | WebHDP reconnects the uniquely identifiable texture when its filename has a transposed letter. |
| Bronze Seal | OBJ and MTL at the archive root | The workflow reports the absent texture and uses the bronze material colour. |
| Glazed Bowl | OBJ with texture folders | WebHDP relinks the glaze from its new folder and omits the unreadable detail image. The working glaze still appears in the prepared package. |

Choose a sample in the workflow or download its ZIP and upload it unchanged. The results list shows texture repairs, mapped metadata, and attachments. A missing texture image cannot be recovered from a filename alone. When the original image is absent or a match is ambiguous, the result reports the material fallback so that it can be reviewed.

## Use your own model

1. In your WebHDP account, configure an active Zenodo **Sandbox** API credential with deposit write access.
2. Upload a ZIP with one OBJ, glTF or GLB model and any required local dependencies, or a standalone self-contained GLB. The upload limit is 24 MiB. Package assets together, preserving relative paths. For textures, use PNG or JPEG. Follow the errors shown in the run if an archive exceeds expansion limits or lacks required geometry.
3. Select an MSF already in the ZIP, supply a separate CSV or Excel file up to 1 MiB, or enter a title, creator and description. To map a spreadsheet row, set its `filename` column to the model filename or its exact path inside the ZIP. Nested model packages should use the full relative path to avoid ambiguous matches. A standalone GLB needs a separate MSF or form metadata.
4. Check **Processing queue** while preparing the upload, then start the run. The queue shows how many jobs are waiting and running. Once you submit, it also shows your place in line. The run shows preparation, metadata checks and Sandbox upload. You can reload the page and open a recent run. Review warnings and download the prepared model or metadata as soon as they are ready.
5. The confirmed draft includes the model and five metadata attachments. These are Europeana EDM XML, IIIF Presentation JSON, METS/MODS XML, CIDOC-CRM RDF/XML, and JSON-LD. Sample drafts also contain a preview image. Open your draft in Sandbox using the Zenodo account that owns the credential.

See [the MSF and upload workflow](../workflows/publication-upload-msf.md) for the wider batch pipeline, custom mappings and production repository workflows.

## Run a 15-minute demonstration

Prepare a dedicated account before the event. Keep its generated credentials in a private file and share them with participants as they begin. The account accepts the three example packages and their original metadata. Participants sharing this WebHDP account each have a separate result history bound to their sign-in.

Open the account window at the start of the presentation. Have attendees start in the first few minutes so the queue has time to drain. Four CPU jobs run concurrently, and subsequent jobs advance in arrival order. Queue and workspace capacity for 20 demo submissions is reserved from regular traffic. The account stops accepting sign-ins and its tokens expire 15 minutes after opening. Work already accepted can finish in the queue. Visitors can use the public library at any time.

Attendees can see and download their confirmed draft attachments in WebHDP and open a read-only preview of their own sample draft in Sandbox. The preview link belongs to that run and expires the next day. The public Sandbox example in the sample library shows what the same files look like on a published record.

### Operator commands

Run the commands below inside the deployed backend container, in `/app`. Choose a private directory, outside any public assets, owned by the application's runtime UID. The first command creates the credentials file with mode 0600. Copy it through your normal private delivery channel.

```sh
python -m scripts.model_publication prepare-demo --output /app/instance/demo-credentials.json
python -m scripts.model_publication open-demo <demo-email>
python -m scripts.model_publication close-demo <demo-email>
```

Each prepared account can open one window. Prepare a fresh account for another event. Close a window early if the credentials were distributed beyond the intended attendees. The demo worker uses WebHDP's existing `ZENODO_SANDBOX_API_KEY` on the server.

### Deployment and recovery

Include `docker-compose.model-publication.yml` after the main and hosting profiles. Use the same released backend image for the dedicated worker and API. Both need the same persistent `/app/instance` mount on a single Linux host. Only the dedicated worker starts queue processing. The ordinary Celery services can continue running existing pipelines. The feature stays unavailable until the worker reports a fresh heartbeat and the user has an appropriate Sandbox credential.

The queue and workspaces are under `instance/model-publication`. Finished results expire locally after 48 hours. This leaves the remote drafts in the owner's Sandbox account. After a worker interruption, queued jobs continue, and confirmed remote draft IDs are reused. If a draft creation request had an uncertain outcome, review the Sandbox account before repeating the job. An operator can read the private `remote-draft.json` checkpoint and `results/lod-generation.json` validation report in the job workspace.

The guided application creates drafts. A server operator can use the following command for a verified demonstration sample with its original metadata. Check the result using an anonymous browser, then set `WEBHDP_MODEL_PUBLICATION_PUBLISHED_EXAMPLE` to that Sandbox record URL for the public sample page.

```sh
python -m scripts.model_publication publish-sample <completed-demo-job-id> --confirm-sandbox publish
```
