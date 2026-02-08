import {defineType, defineField, defineArrayMember} from 'sanity'
import {DocumentTextIcon} from '@sanity/icons'

/**
 * Root document type representing a design document from Google Docs.
 * Acts as the root of a graph where sections, components, and data flows
 * are interconnected nodes.
 */
export const designDocument = defineType({
  name: 'designDocument',
  title: 'Design Document',
  type: 'document',
  icon: DocumentTextIcon,
  fields: [
    defineField({
      name: 'title',
      title: 'Document Title',
      type: 'string',
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: 'googleDocId',
      title: 'Google Doc ID',
      type: 'string',
      description: 'The ID of the source Google Doc for write-back',
    }),
    defineField({
      name: 'googleDocUrl',
      title: 'Google Doc URL',
      type: 'url',
    }),
    defineField({
      name: 'summary',
      title: 'Document Summary',
      type: 'text',
      description: 'AI-generated summary of the document purpose',
    }),
    defineField({
      name: 'sections',
      title: 'Document Sections',
      type: 'array',
      of: [
        defineArrayMember({
          type: 'reference',
          to: [{type: 'documentSection'}],
        }),
      ],
      description: 'Ordered list of sections in the document',
    }),
    defineField({
      name: 'components',
      title: 'Technical Components',
      type: 'array',
      of: [
        defineArrayMember({
          type: 'reference',
          to: [{type: 'technicalComponent'}],
        }),
      ],
      description: 'All technical components described in this document',
    }),
    defineField({
      name: 'dataFlows',
      title: 'Data Flows',
      type: 'array',
      of: [
        defineArrayMember({
          type: 'reference',
          to: [{type: 'dataFlow'}],
        }),
      ],
      description: 'Data flow connections between components',
    }),
    defineField({
      name: 'complianceIssues',
      title: 'Compliance Issues',
      type: 'array',
      of: [
        defineArrayMember({
          type: 'reference',
          to: [{type: 'complianceIssue'}],
        }),
      ],
      description: 'Privacy/compliance issues identified in review',
    }),
    defineField({
      name: 'status',
      title: 'Review Status',
      type: 'string',
      options: {
        list: [
          {title: 'Draft', value: 'draft'},
          {title: 'Under Review', value: 'under_review'},
          {title: 'Issues Identified', value: 'issues_identified'},
          {title: 'Modifications Pending', value: 'modifications_pending'},
          {title: 'Approved', value: 'approved'},
        ],
        layout: 'radio',
      },
      initialValue: 'draft',
    }),
    defineField({
      name: 'lastSyncedAt',
      title: 'Last Synced',
      type: 'datetime',
      description: 'When the document was last synced from Google Docs',
    }),
    defineField({
      name: 'lastModifiedAt',
      title: 'Last Modified',
      type: 'datetime',
      description: 'When modifications were last written back to Google Docs',
    }),
  ],
  preview: {
    select: {
      title: 'title',
      status: 'status',
    },
    prepare({title, status}) {
      return {
        title: title || 'Untitled Document',
        subtitle: status ? `Status: ${status}` : undefined,
      }
    },
  },
})
