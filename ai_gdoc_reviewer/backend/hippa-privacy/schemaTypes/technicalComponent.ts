import {defineType, defineField, defineArrayMember} from 'sanity'
import {ComponentIcon} from '@sanity/icons'

/**
 * A technical component described in the design document.
 * Examples: API endpoints, databases, services, data stores, etc.
 * The description field should include the tech stack (e.g., "PostgreSQL database for patient records").
 */
export const technicalComponent = defineType({
  name: 'technicalComponent',
  title: 'Technical Component',
  type: 'document',
  icon: ComponentIcon,
  fields: [
    defineField({
      name: 'name',
      title: 'Component Name',
      type: 'string',
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: 'componentType',
      title: 'Component Type',
      type: 'string',
      options: {
        list: [
          {title: 'API Endpoint', value: 'api'},
          {title: 'Database', value: 'database'},
          {title: 'Service', value: 'service'},
          {title: 'Data Store', value: 'datastore'},
          {title: 'External System', value: 'external'},
          {title: 'User Interface', value: 'ui'},
          {title: 'Authentication', value: 'auth'},
          {title: 'Message Queue', value: 'queue'},
          {title: 'Storage', value: 'storage'},
          {title: 'LLM', value: 'llm'},
          {title: 'Other', value: 'other'},
        ],
      },
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: 'description',
      title: 'Description',
      type: 'text',
      description: 'What this component does, including the tech stack (e.g., "Node.js Express REST API for patient data")',
    }),
    defineField({
      name: 'technicalDetails',
      title: 'Technical Details',
      type: 'array',
      of: [defineArrayMember({type: 'block'})],
      description: 'Detailed technical specifications',
    }),
    defineField({
      name: 'dataHandled',
      title: 'Data Handled',
      type: 'array',
      of: [
        defineArrayMember({
          type: 'object',
          fields: [
            defineField({
              name: 'dataType',
              title: 'Data Type',
              type: 'string',
            }),
            defineField({
              name: 'isPHI',
              title: 'Contains PHI',
              type: 'boolean',
              description: 'Does this data include Protected Health Information?',
            }),
            defineField({
              name: 'isPII',
              title: 'Contains PII',
              type: 'boolean',
              description: 'Does this data include Personally Identifiable Information?',
            }),
            defineField({
              name: 'sensitivity',
              title: 'Sensitivity Level',
              type: 'string',
              options: {
                list: ['low', 'medium', 'high', 'critical'],
              },
            }),
          ],
        }),
      ],
      description: 'Types of data this component handles',
    }),
    defineField({
      name: 'privacyMeasures',
      title: 'Privacy Measures',
      type: 'array',
      of: [defineArrayMember({type: 'string'})],
      description: 'Privacy controls in place (e.g., "encryption at rest", "audit logging", "role-based access control")',
    }),
    defineField({
      name: 'sourceSection',
      title: 'Source Section',
      type: 'reference',
      to: [{type: 'documentSection'}],
      description: 'The document section where this component is described',
    }),
    defineField({
      name: 'incomingFlows',
      title: 'Incoming Data Flows',
      type: 'array',
      of: [
        defineArrayMember({
          type: 'reference',
          to: [{type: 'dataFlow'}],
        }),
      ],
      description: 'Data flows coming into this component',
    }),
    defineField({
      name: 'outgoingFlows',
      title: 'Outgoing Data Flows',
      type: 'array',
      of: [
        defineArrayMember({
          type: 'reference',
          to: [{type: 'dataFlow'}],
        }),
      ],
      description: 'Data flows going out of this component',
    }),
    defineField({
      name: 'relatedIssues',
      title: 'Related Compliance Issues',
      type: 'array',
      of: [
        defineArrayMember({
          type: 'reference',
          to: [{type: 'complianceIssue'}],
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
      title: 'name',
      type: 'componentType',
      description: 'description',
    },
    prepare({title, type, description}) {
      return {
        title: title || 'Unnamed Component',
        subtitle: `${type || 'unknown'}${description ? ` - ${description.slice(0, 50)}` : ''}`,
      }
    },
  },
})
