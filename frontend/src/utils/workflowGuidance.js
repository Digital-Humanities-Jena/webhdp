// IDs stay aligned with persisted workflow steps; display numbering follows the chosen path.
export const workflowSteps = [
  { id: 1, name: 'Upload' },
  { id: 2, name: 'Check spreadsheet' },
  { id: 3, name: 'Review Files' },
  { id: 4, name: 'Describe records' },
  { id: 5, name: 'Linked metadata' },
  { id: 6, name: 'Choose processing' },
  { id: 7, name: 'Review & start' },
]

export const workflowGuidance = {
  1: {
    title: 'Start with your source files',
    hint: 'A session keeps your files and workflow settings together. Uploading does not publish a record.',
    detail: 'Use one self-contained model, such as a GLB, for your first run. For a model with separate textures or several models, choose a batch and keep the related files together.',
  },
  2: {
    title: 'Match spreadsheet rows to your files',
    hint: 'The metadata source file (MSF) is a spreadsheet describing each model. Resolve blocking issues before continuing.',
    detail: 'Check filenames first, then required metadata. Review any proposed repairs and the record plan: a new record, a new version of an existing record, or a skipped item. Skipped rows will not be processed.',
  },
  3: {
    title: 'Choose the models to process',
    hint: 'Select the main model in each file group. Related textures and materials belong with that model.',
    detail: 'A bundle is a model and its supporting files. Expand a group to check its contents. Cloud Storage downloads are backups of uploaded inputs; generated results become available after processing.',
  },
  4: {
    title: 'Describe the records people will find',
    hint: 'Check titles, creators, descriptions and licences. In a batch, review how spreadsheet columns fill these fields.',
    detail: 'These descriptions accompany the files in Zenodo. Required fields must be filled before you continue. Saving this form prepares metadata; it does not publish a record.',
  },
  5: {
    title: 'Prepare metadata for reuse',
    hint: 'Choose a template, review the preview and resolve validation errors before continuing.',
    detail: 'EDM means Europeana Data Model. LOD here means linked open data, not a lower-detail 3D model. The workflow can produce EDM, CIDOC-CRM, METS/MODS and JSON-LD; check the chosen pipeline for the outputs it generates. Use the default template unless your project needs another mapping.',
  },
  6: {
    title: 'Choose the result you need',
    hint: 'A pipeline is the sequence of processing tasks. Review its steps before continuing to the final summary.',
    detail: 'Choose rendering when you need thumbnail images of a 3D model. Metadata-only processing does not render thumbnails. Rendering on a server requires access to HPC (high-performance computing); readiness is checked before processing starts.',
  },
  7: {
    title: 'Check the destination before starting',
    hint: 'Sandbox is the Zenodo test repository. Production is the live repository. Each needs a key for that environment.',
    detail: 'Confirm & Process starts the selected tasks and may create or update Zenodo drafts. A completed processing job is not proof of publication. Afterwards, inspect the generated files, warnings and record status. Track a submitted job under Submissions if you leave this page.',
  },
}
