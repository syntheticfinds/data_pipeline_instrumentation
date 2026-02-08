import {defineType, defineField} from 'sanity'
import {FolderIcon} from '@sanity/icons'

export const hipaaSubpart = defineType({
  name: 'hipaaSubpart',
  title: 'HIPAA Subpart',
  type: 'document',
  icon: FolderIcon,
  fields: [
    defineField({
      name: 'identifier',
      title: 'Subpart Identifier',
      type: 'string',
      description: 'e.g., "A", "B", "C", "D", "E"',
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: 'title',
      title: 'Title',
      type: 'string',
      description: 'e.g., "General Provisions", "Preemption of State Law"',
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: 'part',
      title: 'Parent Part',
      type: 'reference',
      to: [{type: 'hipaaPart'}],
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: 'description',
      title: 'Description',
      type: 'text',
      description: 'Overview of what this subpart covers',
    }),
    defineField({
      name: 'aiRelevanceSummary',
      title: 'AI Relevance Summary',
      type: 'text',
      description: 'Why this subpart matters for AI system development in healthcare',
    }),
  ],
  preview: {
    select: {
      title: 'title',
      identifier: 'identifier',
      partNumber: 'part.partNumber',
    },
    prepare({title, identifier, partNumber}) {
      return {
        title: `Subpart ${identifier}: ${title}`,
        subtitle: partNumber ? `Part ${partNumber}` : '',
      }
    },
  },
})
