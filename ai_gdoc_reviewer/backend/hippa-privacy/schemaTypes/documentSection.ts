import {defineType, defineField, defineArrayMember} from 'sanity'
import {BlockContentIcon} from '@sanity/icons'

/**
 * A section within a design document.
 * Contains Portable Text content and references to components it describes.
 */
export const documentSection = defineType({
  name: 'documentSection',
  title: 'Document Section',
  type: 'document',
  icon: BlockContentIcon,
  fields: [
    defineField({
      name: 'title',
      title: 'Section Title',
      type: 'string',
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: 'headingLevel',
      title: 'Heading Level',
      type: 'number',
      options: {
        list: [1, 2, 3, 4, 5, 6],
      },
      initialValue: 2,
    }),
    defineField({
      name: 'originalText',
      title: 'Original Text',
      type: 'text',
      description: 'The raw text from the Google Doc for this section',
    }),
    defineField({
      name: 'content',
      title: 'Structured Content',
      type: 'array',
      of: [
        defineArrayMember({
          type: 'block',
          styles: [
            {title: 'Normal', value: 'normal'},
            {title: 'H1', value: 'h1'},
            {title: 'H2', value: 'h2'},
            {title: 'H3', value: 'h3'},
            {title: 'Quote', value: 'blockquote'},
          ],
          marks: {
            decorators: [
              {title: 'Strong', value: 'strong'},
              {title: 'Emphasis', value: 'em'},
              {title: 'Code', value: 'code'},
              {title: 'Highlight', value: 'highlight'},
            ],
            annotations: [
              {
                name: 'componentRef',
                type: 'object',
                title: 'Component Reference',
                fields: [
                  defineField({
                    name: 'component',
                    type: 'reference',
                    to: [{type: 'technicalComponent'}],
                  }),
                ],
              },
              {
                name: 'complianceNote',
                type: 'object',
                title: 'Compliance Note',
                fields: [
                  defineField({
                    name: 'regulation',
                    type: 'reference',
                    to: [{type: 'hipaaRegulation'}],
                  }),
                  defineField({
                    name: 'note',
                    type: 'text',
                  }),
                ],
              },
            ],
          },
        }),
        defineArrayMember({
          type: 'reference',
          to: [{type: 'technicalComponent'}],
          title: 'Embedded Component',
        }),
      ],
      description: 'Portable Text content with component references',
    }),
    defineField({
      name: 'describedComponents',
      title: 'Components Described',
      type: 'array',
      of: [
        defineArrayMember({
          type: 'reference',
          to: [{type: 'technicalComponent'}],
        }),
      ],
      description: 'Technical components described or mentioned in this section',
    }),
    defineField({
      name: 'parentDocument',
      title: 'Parent Document',
      type: 'reference',
      to: [{type: 'designDocument'}],
    }),
    defineField({
      name: 'sectionOrder',
      title: 'Section Order',
      type: 'number',
      description: 'Order of this section in the document',
    }),
    defineField({
      name: 'modifiedContent',
      title: 'Modified Content',
      type: 'array',
      of: [
        defineArrayMember({type: 'block'}),
      ],
      description: 'Agent-modified content pending approval',
    }),
  ],
  preview: {
    select: {
      title: 'title',
      level: 'headingLevel',
      order: 'sectionOrder',
    },
    prepare({title, level, order}) {
      const prefix = level ? '#'.repeat(level) : ''
      return {
        title: `${prefix} ${title || 'Untitled Section'}`,
        subtitle: order !== undefined ? `Section ${order}` : undefined,
      }
    },
  },
})
