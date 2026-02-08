import {defineType, defineField, defineArrayMember} from 'sanity'
import {DocumentIcon} from '@sanity/icons'

export const hipaaRegulation = defineType({
  name: 'hipaaRegulation',
  title: 'HIPAA Regulation',
  type: 'document',
  icon: DocumentIcon,
  fields: [
    defineField({
      name: 'sectionNumber',
      title: 'Section Number',
      type: 'string',
      description: 'e.g., "160.101", "160.103"',
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: 'title',
      title: 'Title',
      type: 'string',
      description: 'e.g., "Statutory basis and purpose", "Definitions"',
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: 'subpart',
      title: 'Subpart',
      type: 'reference',
      to: [{type: 'hipaaSubpart'}],
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: 'content',
      title: 'Regulation Content',
      type: 'array',
      of: [
        defineArrayMember({type: 'block'}),
      ],
      description: 'Full text of the regulation',
    }),
    defineField({
      name: 'citations',
      title: 'Federal Register Citations',
      type: 'array',
      of: [defineArrayMember({type: 'string'})],
      description: 'Source citations (e.g., "78 FR 5687, Jan. 25, 2013")',
    }),
    defineField({
      name: 'keyDefinitions',
      title: 'Key Definitions',
      type: 'array',
      of: [
        defineArrayMember({
          type: 'object',
          fields: [
            defineField({
              name: 'term',
              title: 'Term',
              type: 'string',
              validation: (rule) => rule.required(),
            }),
            defineField({
              name: 'definition',
              title: 'Definition',
              type: 'text',
              validation: (rule) => rule.required(),
            }),
          ],
          preview: {
            select: {
              title: 'term',
              subtitle: 'definition',
            },
          },
        }),
      ],
      description: 'Key terms defined in this section',
    }),
    defineField({
      name: 'aiRelevance',
      title: 'AI Relevance',
      type: 'text',
      description: 'Explanation of why this regulation is relevant for AI systems in healthcare',
    }),
    defineField({
      name: 'complianceGuidance',
      title: 'Compliance Guidance',
      type: 'array',
      of: [defineArrayMember({type: 'block'})],
      description: 'How to address this regulation when developing AI systems for healthcare',
    }),
    defineField({
      name: 'riskLevel',
      title: 'Risk Level',
      type: 'string',
      options: {
        list: [
          {title: 'Critical', value: 'critical'},
          {title: 'High', value: 'high'},
          {title: 'Medium', value: 'medium'},
          {title: 'Low', value: 'low'},
        ],
        layout: 'radio',
      },
      description: 'Risk level if this regulation is not properly addressed',
    }),
    defineField({
      name: 'relatedRegulations',
      title: 'Related Regulations',
      type: 'array',
      of: [defineArrayMember({type: 'reference', to: [{type: 'hipaaRegulation'}]})],
      description: 'Other regulations that relate to this one',
    }),
  ],
  preview: {
    select: {
      sectionNumber: 'sectionNumber',
      title: 'title',
      riskLevel: 'riskLevel',
    },
    prepare({sectionNumber, title, riskLevel}) {
      return {
        title: `§ ${sectionNumber}`,
        subtitle: `${title}${riskLevel ? ` [${riskLevel.toUpperCase()}]` : ''}`,
      }
    },
  },
})
