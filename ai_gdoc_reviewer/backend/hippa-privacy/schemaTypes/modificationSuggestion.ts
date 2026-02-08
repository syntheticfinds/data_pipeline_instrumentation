import {defineType, defineField, defineArrayMember} from 'sanity'
import {EditIcon} from '@sanity/icons'

/**
 * A specific modification suggestion for the document.
 * Contains before/after text and can be applied via MCP tools.
 */
export const modificationSuggestion = defineType({
  name: 'modificationSuggestion',
  title: 'Modification Suggestion',
  type: 'document',
  icon: EditIcon,
  fields: [
    defineField({
      name: 'title',
      title: 'Modification Title',
      type: 'string',
      description: 'Brief description of what this modification does',
    }),
    defineField({
      name: 'modificationType',
      title: 'Modification Type',
      type: 'string',
      options: {
        list: [
          {title: 'Text Replacement', value: 'replace'},
          {title: 'Text Insertion', value: 'insert'},
          {title: 'Text Deletion', value: 'delete'},
          {title: 'Section Rewrite', value: 'rewrite'},
          {title: 'Add Component Details', value: 'add_component'},
          {title: 'Add Security Measure', value: 'add_security'},
          {title: 'Add Diagram', value: 'add_diagram'},
        ],
      },
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: 'targetSection',
      title: 'Target Section',
      type: 'reference',
      to: [{type: 'documentSection'}],
    }),
    defineField({
      name: 'targetComponent',
      title: 'Target Component',
      type: 'reference',
      to: [{type: 'technicalComponent'}],
    }),
    defineField({
      name: 'findText',
      title: 'Find Text',
      type: 'text',
      description: 'Exact text to find in the document (for replacements)',
    }),
    defineField({
      name: 'replaceText',
      title: 'Replace With',
      type: 'text',
      description: 'Text to replace with (for replacements)',
    }),
    defineField({
      name: 'insertAfter',
      title: 'Insert After',
      type: 'text',
      description: 'Text after which to insert new content (for insertions)',
    }),
    defineField({
      name: 'insertContent',
      title: 'Content to Insert',
      type: 'array',
      of: [defineArrayMember({type: 'block'})],
      description: 'Rich content to insert',
    }),
    defineField({
      name: 'rationale',
      title: 'Rationale',
      type: 'text',
      description: 'Why this modification is recommended',
    }),
    defineField({
      name: 'relatedIssue',
      title: 'Related Compliance Issue',
      type: 'reference',
      to: [{type: 'complianceIssue'}],
    }),
    defineField({
      name: 'agentAction',
      title: 'Agent Action Used',
      type: 'string',
      options: {
        list: [
          {title: 'Generate (new content)', value: 'generate'},
          {title: 'Transform (modify existing)', value: 'transform'},
          {title: 'Image Generation', value: 'image'},
          {title: 'Manual', value: 'manual'},
        ],
      },
      description: 'Which Sanity agent action was used to create this',
    }),
    defineField({
      name: 'status',
      title: 'Status',
      type: 'string',
      options: {
        list: [
          {title: 'Pending Review', value: 'pending'},
          {title: 'Approved', value: 'approved'},
          {title: 'Applied', value: 'applied'},
          {title: 'Rejected', value: 'rejected'},
        ],
        layout: 'radio',
      },
      initialValue: 'pending',
    }),
    defineField({
      name: 'appliedAt',
      title: 'Applied At',
      type: 'datetime',
      description: 'When this modification was applied to the Google Doc',
    }),
    defineField({
      name: 'diffPreview',
      title: 'Diff Preview',
      type: 'object',
      fields: [
        defineField({
          name: 'before',
          title: 'Before',
          type: 'text',
        }),
        defineField({
          name: 'after',
          title: 'After',
          type: 'text',
        }),
        defineField({
          name: 'contextBefore',
          title: 'Context Before',
          type: 'text',
          description: 'Text immediately before the change for context',
        }),
        defineField({
          name: 'contextAfter',
          title: 'Context After',
          type: 'text',
          description: 'Text immediately after the change for context',
        }),
      ],
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
      type: 'modificationType',
      status: 'status',
      action: 'agentAction',
    },
    prepare({title, type, status, action}) {
      return {
        title: title || 'Untitled Modification',
        subtitle: `${type || 'unknown'} (${action || 'manual'}) - ${status || 'pending'}`,
      }
    },
  },
})
