# Prepare a 3D model for Zenodo Sandbox

[Prepare a 3D model](https://hdp.3drepo.eu/model-publication) packages one model using a CPU worker, checks its texture references, maps its metadata and creates a Zenodo Sandbox draft. The results are available during the run, with a confirmed file inventory when Sandbox finishes receiving them. The workflow is also available from the Uploads area.

## Practise with the 3D tutorial

Open the [3D tutorial](https://hdp.3drepo.eu/tutorial/3d) after signing in.
Select the Glazed Bowl, review its spreadsheet values and start the practice run. The CPU worker checks
the source and relinks or removes texture references using the same repair and
export steps as the Sandbox workflow. The result includes the self-contained
GLB, a preview image, the original CSV and the mapped metadata as JSON. Open
the repair report to see what changed, and compare the CSV row with the mapped
metadata before downloading the files.

The tutorial uses the built-in sample library. It needs only a verified WebHDP
account and the CPU worker. Practice files stay in WebHDP, and you can run the
tutorial again at any time. Only your account can see and download its results.
Finished runs and practice files are available for 48 hours. To generate the five publication metadata formats
and check the result in Zenodo Sandbox, use **Prepare a 3D model** with your own
Sandbox credential.

Practice and Sandbox runs share the allowance shown under **Account → Usage and limits**. Each account can have three requests in progress and submit ten per rolling 24 hours. Its working files and prepared results share a 256 MiB workspace. Finished results can free space as they expire after 48 hours. Pending jobs reserve some space and release the unused portion when processing finishes.

## Try a model

The [sample library](https://hdp.3drepo.eu/model-publication/samples) is public. The ZIP files include original CC0 models and a Metadata Source File (MSF).

| Model | Package | What to look for |
| --- | --- | --- |
| Terracotta Vessel | Nested OBJ, MTL and texture folders | WebHDP preserves the usable references and embeds the textures in the GLB. |
| Painted Floor Tile | glTF with separate geometry and image folders | WebHDP reconnects the uniquely identifiable texture when its filename has a transposed letter. |
| Bronze Seal | OBJ and MTL at the archive root | The workflow reports the absent texture and uses the bronze material colour. |
| Glazed Bowl | OBJ with texture folders | WebHDP relinks the glaze from its new folder and omits the unreadable detail image. The working glaze still appears in the prepared package. |

Choose a sample in the workflow or download its ZIP and upload it unchanged. The results list shows texture repairs, mapped metadata, and attachments. A missing texture image cannot be recovered from a filename alone. When the original image is absent or a match is ambiguous, the result reports the material fallback so that it can be reviewed.

## Use your own model

1. In your WebHDP account, configure an active Zenodo **Sandbox** API credential with deposit write access.
2. Upload a ZIP with one OBJ, glTF or GLB model and any required local dependencies, or a standalone self-contained GLB. The upload limit is 24 MiB. Package assets together, preserving relative paths. For textures, use PNG or JPEG. Follow the errors shown in the run if an archive exceeds expansion limits or lacks required geometry.
3. Select an MSF already in the ZIP, supply a separate CSV or Excel file up to 1 MiB, or enter a title, creator and description. To map a spreadsheet row, set its `filename` column to the model filename or its exact path inside the ZIP. Nested model packages should use the full relative path to avoid ambiguous matches. A standalone GLB needs a separate MSF or form metadata.
4. Review the prepared metadata for a sample and open **Pipeline details** to see the steps. The queue shows how many jobs are waiting and running while you prepare the upload. Once submitted, it also shows your place in line. Use **Inspect texture repairs** to see which files were relinked or omitted. You can reload the page and open a recent run.
5. The confirmed draft includes a self-contained **model.glb** and five metadata attachments. These are Europeana EDM XML, IIIF Presentation JSON, METS/MODS XML, CIDOC-CRM RDF/XML, and JSON-LD. Sample drafts also contain a preview image. Open your draft in Sandbox using the Zenodo account that owns the credential.

The optional **Three-model batch** combines the Glazed Bowl, Painted Floor Tile and Bronze Seal in one ZIP with one shared `metadata.csv`. Choose the batch sample in WebHDP or upload its original ZIP. Review the three mapped rows before submitting. Each model produces its own Sandbox draft with its GLB and metadata attachments.

See [the MSF and upload workflow](../workflows/publication-upload-msf.md) for the wider batch pipeline, custom mappings and production repository workflows.

## Run a live demonstration

Prepare a dedicated account before the event. Keep its generated credentials in a private file and share them with participants as they begin. The account accepts the approved sample packages and their original metadata. Participants sharing this WebHDP account each have a separate result history bound to their sign-in.

Open the account window at the start of the presentation. Have attendees start in the first few minutes so the queue has time to drain. Four CPU jobs run concurrently, and subsequent jobs advance in arrival order. Queue and workspace capacity for 20 demo submissions is reserved from regular traffic. The account stops accepting sign-ins and its tokens expire when the window ends. Use the default 15 minutes or specify a longer window at activation to give attendees time to finish after the talk. Work already accepted can finish in the queue. Visitors can use the public library at any time.

Attendees can see and download their confirmed draft attachments in WebHDP and open a read-only preview of their own sample draft in Sandbox. The preview link belongs to that run and expires the next day. The public Sandbox example in the sample library shows what the same files look like on a published record.

### Operator commands

Run the commands below inside the deployed backend container, in `/app`. Choose a private directory, outside any public assets, owned by the application's runtime UID. The first command creates the credentials file with mode 0600. Copy it through your normal private delivery channel.

```sh
python -m scripts.model_publication prepare-demo --output /app/instance/demo-credentials.json
python -m scripts.model_publication open-demo <demo-email> --minutes 45
python -m scripts.model_publication close-demo <demo-email>
```

Each prepared account can open one window. Prepare a fresh account for another event. Close a window early if the credentials were distributed beyond the intended attendees. The demo worker uses WebHDP's existing `ZENODO_SANDBOX_API_KEY` on the server.

### Deployment and recovery

Include `docker-compose.model-publication.yml` after the main and hosting profiles. Set `WEBHDP_INSTANCE_PATH` to the persistent host directory that the API and dedicated worker both mount at `/app/instance`. Use the same backend image for both services. Set `WEBHDP_BACKEND_IMAGE` to that image if the hosting profile uses a custom name or tag. The ordinary Celery worker continues processing the existing pipelines. Practice runs are available when the dedicated worker reports a fresh tutorial heartbeat. Sandbox drafts also require an authorized Sandbox credential. The site tour and public sample library remain available on installations that run without this profile.

Set `LOCAL_EDM_VALIDATOR_URL` to a validator reachable from the dedicated worker. When the validator runs in the same Compose project with `docker-compose.edm-validator.yml`, set `LOCAL_EDM_VALIDATOR_URL=http://local-edm-validator:8080` in `.env`. The host-side loopback address is for checks run on the host. Test the validator from the worker's network before enabling Sandbox runs. The CPU practice tutorial can run without the validator or a Zenodo credential.

The queue and workspaces are under `instance/model-publication`. Finished results expire locally after 48 hours. This leaves the remote drafts in the owner's Sandbox account. After a worker interruption, queued jobs continue, and confirmed remote draft IDs are reused. If a draft creation request had an uncertain outcome, review the Sandbox account before repeating the job. An operator can read the private `remote-draft.json` checkpoint and `results/lod-generation.json` validation report in the job workspace.

The guided application creates drafts. A server operator can use the following command for a verified demonstration sample with its original metadata. Check the result using an anonymous browser, then set `WEBHDP_MODEL_PUBLICATION_PUBLISHED_EXAMPLE` to that Sandbox record URL for the public sample page.

```sh
python -m scripts.model_publication publish-sample <completed-demo-job-id> --confirm-sandbox publish
```
