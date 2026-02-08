import {defineType, defineField, defineArrayMember} from 'sanity'
import {WarningOutlineIcon} from '@sanity/icons'

/**
 * A compliance issue identified during privacy review.
 * Links to relevant regulations, components, and sections.
 */
export const complianceIssue = defineType({
  name: 'complianceIssue',
  title: 'Compliance Issue',
  type: 'document',
  icon: WarningOutlineIcon,
  fields: [
    defineField({
      name: 'title',
      title: 'Issue Title',
      type: 'string',
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: 'originalComment',
      title: 'Original Review Comment',
      type: 'text',
      description: 'The comment from the privacy review',
    }),
    defineField({
      name: 'severity',
      title: 'Severity',
      type: 'string',
      options: {
        list: [
          {title: 'Low', value: 'low'},
          {title: 'Medium', value: 'medium'},
          {title: 'High', value: 'high'},
          {title: 'Critical', value: 'critical'},
        ],
        layout: 'radio',
      },
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: 'description',
      title: 'Issue Description',
      type: 'array',
      of: [defineArrayMember({type: 'block'})],
      description: 'Detailed description of the compliance issue',
    }),
    defineField({
      name: 'affectedRegulations',
      title: 'Affected Regulations',
      type: 'array',
      of: [
        defineArrayMember({
          type: 'reference',
          to: [{type: 'hipaaRegulation'}],
        }),
      ],
      description: 'HIPAA regulations this issue relates to',
    }),
    defineField({
      name: 'affectedComponents',
      title: 'Affected Components',
      type: 'array',
      of: [
        defineArrayMember({
          type: 'reference',
          to: [{type: 'technicalComponent'}],
        }),
      ],
    }),
    defineField({
      name: 'affectedDataFlows',
      title: 'Affected Data Flows',
      type: 'array',
      of: [
        defineArrayMember({
          type: 'reference',
          to: [{type: 'dataFlow'}],
        }),
      ],
    }),
    defineField({
      name: 'affectedSections',
      title: 'Affected Document Sections',
      type: 'array',
      of: [
        defineArrayMember({
          type: 'reference',
          to: [{type: 'documentSection'}],
        }),
      ],
    }),
    defineField({
      name: 'targetQuote',
      title: 'Target Quote',
      type: 'text',
      description: 'The exact text from the document that triggered this issue',
    }),
    defineField({
      name: 'suggestedFix',
      title: 'Suggested Fix',
      type: 'array',
      of: [defineArrayMember({type: 'block'})],
      description: 'Recommended remediation steps',
    }),
    defineField({
      name: 'researchContext',
      title: 'Research Context',
      type: 'text',
      description: 'Web research context used to generate the suggestion',
    }),
    defineField({
      name: 'modificationSuggestions',
      title: 'Modification Suggestions',
      type: 'array',
      of: [
        defineArrayMember({
          type: 'reference',
          to: [{type: 'modificationSuggestion'}],
        }),
      ],
      description: 'Specific document modifications suggested to resolve this issue',
    }),
    defineField({
      name: 'parentDocument',
      title: 'Parent Document',
      type: 'reference',
      to: [{type: 'designDocument'}],
    }),
  ],
  preview: {
    select: {
      title: 'title',
      severity: 'severity',
    },
    prepare({title, severity}) {
      const severityEmoji = {
        low: 'o',
        medium: '!',
        high: '!!',
        critical: '!!!',
      }
      return {
        title: `[${severityEmoji[severity as keyof typeof severityEmoji] || '?'}] ${title || 'Untitled Issue'}`,
        subtitle: severity || 'unknown',
      }
    },
  },
})
