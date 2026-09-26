export function georeferencingInputError(files) {
  const nameOf = file => file.filename || file.name || file.relative_path || file.absolute_path || ''
  const referenceCount = file => {
    const own = /\.tiff?$/i.test(nameOf(file)) ? 1 : 0
    return own + (file.children || []).reduce((sum, child) => sum + referenceCount(child), 0)
  }
  for (const file of files) {
    if (!/\.glb$/i.test(nameOf(file))) {
      return 'Choose a static GLB as the main file in each georeferencing bundle.'
    }
    if (referenceCount(file) !== 1) {
      return `${nameOf(file)} needs exactly one reference GeoTIFF in its bundle. Upload a GLB and TIF/TIFF with the same filename stem together as a batch, list the GLB in the metadata spreadsheet, then review the file groups.`
    }
  }
  return ''
}
