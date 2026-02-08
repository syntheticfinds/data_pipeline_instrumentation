import {defineType, defineField, defineArrayMember} from 'sanity'
import {TransferIcon} from '@sanity/icons'

/**
 * A data flow connection between technical components.
 * Represents how data moves through the system.
 */
export const dataFlow = defineType({
  name: 'dataFlow',
  title: 'Data Flow',
  type: 'document',
  icon: TransferIcon,
  fields: [
    defineField({
      name: 'name',
      title: 'Flow Name',
      type: 'string',
      description: 'Descriptive name for this data flow',
    }),
    defineField({
      name: 'sourceComponent',
      title: 'Source Component',
      type: 'reference',
      to: [{type: 'technicalComponent'}],
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: 'targetComponent',
      title: 'Target Component',
      type: 'reference',
      to: [{type: 'technicalComponent'}],
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: 'dataTypes',
      title: 'Data Types Transferred',
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
              name: 'containsPHI',
              title: 'Contains PHI',
              type: 'boolean',
            }),
            defineField({
              name: 'containsPII',
              title: 'Contains PII',
              type: 'boolean',
            }),
          ],
        }),
      ],
    }),
    defineField({
      name: 'protocol',
      title: 'Transfer Protocol',
      type: 'string',
      options: {
        list: [
          {title: 'HTTPS/REST', value: 'https'},
          {title: 'gRPC', value: 'grpc'},
          {title: 'GraphQL', value: 'graphql'},
          {title: 'WebSocket', value: 'websocket'},
          {title: 'Message Queue', value: 'queue'},
          {title: 'Database Connection', value: 'database'},
          {title: 'File Transfer', value: 'file'},
          {title: 'Internal', value: 'internal'},
          {title: 'Other', value: 'other'},
        ],
      },
    }),
    defineField({
      name: 'encryption',
      title: 'Encryption',
      type: 'object',
      fields: [
        defineField({
          name: 'inTransit',
          title: 'Encrypted in Transit',
          type: 'boolean',
        }),
        defineField({
          name: 'transitProtocol',
          title: 'Transit Encryption Protocol',
          type: 'string',
          description: 'e.g., TLS 1.2+, TLS 1.3',
        }),
        defineField({
          name: 'atRest',
          title: 'Encrypted at Rest',
          type: 'boolean',
        }),
        defineField({
          name: 'restAlgorithm',
          title: 'At-Rest Encryption Algorithm',
          type: 'string',
          description: 'e.g., AES-256-GCM',
        }),
      ],
    }),
    defineField({
      name: 'authentication',
      title: 'Authentication Method',
      type: 'string',
      options: {
        list: [
          {title: 'API Key', value: 'api_key'},
          {title: 'OAuth 2.0', value: 'oauth2'},
          {title: 'JWT', value: 'jwt'},
          {title: 'mTLS', value: 'mtls'},
          {title: 'Basic Auth', value: 'basic'},
          {title: 'None', value: 'none'},
          {title: 'Other', value: 'other'},
        ],
      },
    }),
    defineField({
      name: 'accessControl',
      title: 'Access Control',
      type: 'text',
      description: 'Description of access control mechanisms',
    }),
    defineField({
      name: 'auditLogging',
      title: 'Audit Logging',
      type: 'object',
      fields: [
        defineField({
          name: 'enabled',
          title: 'Logging Enabled',
          type: 'boolean',
        }),
        defineField({
          name: 'details',
          title: 'What is Logged',
          type: 'text',
          description: 'Details about what audit data is captured',
        }),
        defineField({
          name: 'retention',
          title: 'Retention Period',
          type: 'string',
          description: 'e.g., 6 years per HIPAA requirements',
        }),
      ],
    }),
    defineField({
      name: 'sourceSection',
      title: 'Source Section',
      type: 'reference',
      to: [{type: 'documentSection'}],
      description: 'The document section where this data flow is described',
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
      name: 'name',
      sourceName: 'sourceComponent.name',
      targetName: 'targetComponent.name',
    },
    prepare({name, sourceName, targetName}) {
      const flowName = name || `${sourceName || '?'} -> ${targetName || '?'}`
      return {
        title: flowName,
      }
    },
  },
})
