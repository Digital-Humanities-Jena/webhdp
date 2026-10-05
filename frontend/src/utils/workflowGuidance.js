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
    detail: 'These descriptions accompany the files in Zenodo. Errors beside a field link to that input. Draft edits are saved automatically and retained in this browser tab for reload recovery. Retry a failed save before closing the tab. In a batch, choose filenames to review individual descriptions.',
  },
  5: {
    title: 'Prepare metadata for reuse',
    hint: 'Choose a template, review the preview and resolve validation errors before continuing.',
    detail: 'EDM means Europeana Data Model. LOD means linked open data. Review titles, creators, rights, source labels and generated defaults before expanding technical output. Choose batch previews by filename; spreadsheet checks cover all source rows, but validation covers the selected preview. IIIF handles images, models and timed media; check the chosen pipeline for its enabled exports.',
  },
  6: {
    title: 'Choose the result you need',
    hint: 'A pipeline is the sequence of processing tasks. Review its steps before continuing to the final summary.',
    detail: 'Read each outcome to distinguish local results, Zenodo draft creation, upload and publication. The recommendation favors compatible processing without publication or an HPC job. Expand Outputs and requirements for formats and resources. Rendering needs an HPC allocation; metadata-only processing needs a Zenodo credential. Readiness is checked before processing starts.',
  },
  7: {
    title: 'Check the destination before starting',
    hint: 'Sandbox is the Zenodo test repository. Production is the live repository. Each needs a key for that environment.',
    detail: 'Submission readiness checks every selected source and saved setting automatically. Follow its review links to fix blockers, then Check again. Expand Checks still unverified for runtime requirements. Confirm & Process rechecks before allocating resources and may create or update Zenodo drafts. Afterwards, inspect generated files, warnings and record status; completion alone does not establish publication. Track the run under Submissions if you leave this page.',
  },
}
