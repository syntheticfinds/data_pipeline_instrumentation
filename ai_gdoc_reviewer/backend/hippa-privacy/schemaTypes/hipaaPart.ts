import {defineType, defineField} from 'sanity'
import {DocumentTextIcon} from '@sanity/icons'

export const hipaaPart = defineType({
  name: 'hipaaPart',
  title: 'HIPAA Part',
  type: 'document',
  icon: DocumentTextIcon,
  fields: [
    defineField({
      name: 'partNumber',
      title: 'Part Number',
      type: 'string',
      description: 'e.g., "160", "164"',
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: 'title',
      title: 'Title',
      type: 'string',
      description: 'e.g., "General Administrative Requirements"',
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: 'cfrTitle',
      title: 'CFR Title',
      type: 'string',
      description: 'e.g., "45 CFR Part 160"',
    }),
    defineField({
      name: 'authority',
      title: 'Legal Authority',
      type: 'text',
      description: 'Statutory authority citations',
    }),
    defineField({
      name: 'source',
      title: 'Source',
      type: 'string',
      description: 'Federal Register reference (e.g., "65 FR 82798, Dec. 28, 2000")',
    }),
    defineField({
      name: 'effectiveDate',
      title: 'Effective Date',
      type: 'date',
    }),
    defineField({
      name: 'summary',
      title: 'Summary',
      type: 'text',
      description: 'Brief overview of what this part covers',
    }),
  ],
  preview: {
    select: {
      title: 'title',
      partNumber: 'partNumber',
    },
    prepare({title, partNumber}) {
      return {
        title: `Part ${partNumber}`,
        subtitle: title,
      }
    },
  },
})
