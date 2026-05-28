import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import { RouterLinkStub } from './helpers/router.mjs'
import credits from '../src/content/credits.json'
import CreditsView from '../src/views/public/CreditsView.vue'

describe('credits content', () => {
  it('keeps the editable credits data in the expected shape', () => {
    expect(credits.leadDeveloper.name).toBe('Dominik Ukolov')
    expect(credits.leadDeveloper.role).toBe('Initiator and lead developer')
    expect(credits.leadDeveloper.email).toBe('dominik.ukolov@uni-jena.de')
    expect(credits.leadDeveloper.orcid).toBe('0000-0002-7904-3892')
    expect(credits.leadDeveloper.affiliations).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ text: 'Professorship for Digital Humanities (Image/Object), Friedrich Schiller University Jena' }),
        expect.objectContaining({ text: 'Research Group DIGITAL ORGANOLOGY, Leipzig University', emphasis: true }),
      ])
    )

    expect(Array.isArray(credits.contributors)).toBe(true)
    credits.contributors.forEach((contributor) => {
      expect(contributor.name).toEqual(expect.any(String))
      if (contributor.affiliation !== undefined) {
        expect(contributor.affiliation).toEqual(expect.any(String))
      }
    })

    expect(credits.projects).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: '3dbigdataspace',
          officialName: '3D Big Data for the Data Space for Cultural Heritage',
          grantAgreement: '101173385',
          url: 'https://3dbigdataspace.eu/',
        }),
        expect.objectContaining({
          id: 'infinity',
          officialName: 'Multidimensional knowledge-based annotation for ethical context-aware heritage data life cycles',
          grantAgreement: '101233051',
          programme: 'Horizon Europe',
        }),
      ])
    )
  })
})

describe('CreditsView', () => {
  it('renders lead developer, affiliations, EU project context, and contributor empty state', () => {
    const wrapper = mount(CreditsView, {
      global: {
        stubs: {
          RouterLink: RouterLinkStub,
        },
      },
    })

    expect(wrapper.get('h1').text()).toBe('Credits')
    expect(wrapper.text()).toContain('Dominik Ukolov')
    expect(wrapper.text()).toContain('Initiator and lead developer')
    expect(wrapper.text()).toContain('Professorship for Digital Humanities (Image/Object), Friedrich Schiller University Jena')
    expect(wrapper.text()).toContain('Research Group DIGITAL ORGANOLOGY, Leipzig University')
    expect(wrapper.text()).toContain('ORCID 0000-0002-7904-3892')
    expect(wrapper.text()).toContain('Additional contributing developers can be added by editing the credits data file.')
    expect(wrapper.text()).toContain('3DBigDataSpace')
    expect(wrapper.text()).toContain('3D Big Data for the Data Space for Cultural Heritage')
    expect(wrapper.text()).toContain('No. 101173385')
    expect(wrapper.text()).toContain('INFINITY')
    expect(wrapper.text()).toContain('Multidimensional knowledge-based annotation for ethical context-aware heritage data life cycles')
    expect(wrapper.text()).toContain('No. 101233051')

    expect(wrapper.find('a[href="https://3dbigdataspace.eu/"]').exists()).toBe(true)
    expect(wrapper.find('a[href="https://cordis.europa.eu/project/id/101233051"]').exists()).toBe(true)
    expect(wrapper.find('a[href="https://orcid.org/0000-0002-7904-3892"]').exists()).toBe(true)
  })
})
