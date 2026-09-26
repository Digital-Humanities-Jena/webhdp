import { describe, it, expect } from 'vitest'
import { georeferencingInputError } from '../src/utils/georeferencingInputs.js'

describe('georeferencing bundles', () => {
  it('accepts a reference nested in each selected GLB bundle', () => {
    expect(georeferencingInputError([
      { filename: 'site.GLB', children: [{ name: 'imagery', children: [{ name: 'reference.TIFF' }] }] },
      { filename: 'second.glb', children: [{ name: 'second.tif' }] }
    ])).toBe('')
  })
  it('does not borrow another record’s reference', () => {
    expect(georeferencingInputError([
      { name: 'one.glb', children: [{ name: 'one.tif' }] }, { name: 'two.glb' }
    ])).toContain('two.glb needs exactly one')
  })
  it('rejects ambiguous references and wrong primary files', () => {
    expect(georeferencingInputError([{ name: 'site.glb', children: [{ name: 'a.tif' }, { name: 'b.tif' }] }])).toContain('exactly one')
    expect(georeferencingInputError([{ name: 'site.obj' }])).toContain('static GLB')
  })
})
