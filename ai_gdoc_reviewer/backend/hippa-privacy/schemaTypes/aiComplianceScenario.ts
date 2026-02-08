import {defineType, defineField, defineArrayMember} from 'sanity'
import {RobotIcon} from '@sanity/icons'

export const aiComplianceScenario = defineType({
  name: 'aiComplianceScenario',
  title: 'AI Compliance Scenario',
  type: 'document',
  icon: RobotIcon,
  fields: [
    defineField({
      name: 'title',
      title: 'Scenario Title',
      type: 'string',
      description: 'e.g., "Training ML Models on Patient Data"',
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: 'slug',
      title: 'Slug',
      type: 'slug',
      options: {
        source: 'title',
        maxLength: 96,
      },
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: 'description',
      title: 'Scenario Description',
      type: 'text',
      description: 'Detailed description of the AI development scenario',
      validation: (rule) => rule.required(),
    }),
    defineField({
      name: 'category',
      title: 'Category',
      type: 'string',
      options: {
        list: [
          {title: 'Data Collection', value: 'data-collection'},
          {title: 'Data Processing', value: 'data-processing'},
          {title: 'Model Training', value: 'model-training'},
          {title: 'Model Deployment', value: 'model-deployment'},
          {title: 'Data Sharing', value: 'data-sharing'},
          {title: 'Third-Party Services', value: 'third-party'},
          {title: 'Patient Interaction', value: 'patient-interaction'},
          {title: 'Research', value: 'research'},
        ],
        layout: 'dropdown',
      },
    }),
    defineField({
      name: 'relevantRegulations',
      title: 'Relevant HIPAA Regulations',
      type: 'array',
      of: [defineArrayMember({type: 'reference', to: [{type: 'hipaaRegulation'}]})],
      description: 'HIPAA regulations that apply to this scenario',
    }),
    defineField({
      name: 'complianceSteps',
      title: 'Compliance Steps',
      type: 'array',
      of: [
        defineArrayMember({
          type: 'object',
          fields: [
            defineField({
              name: 'step',
              title: 'Step',
              type: 'string',
              validation: (rule) => rule.required(),
            }),
            defineField({
              name: 'description',
              title: 'Description',
              type: 'text',
            }),
            defineField({
              name: 'regulationReference',
              title: 'Regulation Reference',
              type: 'reference',
              to: [{type: 'hipaaRegulation'}],
            }),
          ],
          preview: {
            select: {
              title: 'step',
            },
          },
        }),
      ],
      description: 'Step-by-step compliance checklist',
    }),
    defineField({
      name: 'riskAssessment',
      title: 'Risk Assessment',
      type: 'array',
      of: [defineArrayMember({type: 'block'})],
      description: 'Assessment of risks and potential penalties',
    }),
    defineField({
      name: 'bestPractices',
      title: 'Best Practices',
      type: 'array',
      of: [defineArrayMember({type: 'block'})],
      description: 'Recommended best practices for this scenario',
    }),
    defineField({
      name: 'overallRiskLevel',
      title: 'Overall Risk Level',
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
    }),
    defineField({
      name: 'commonMistakes',
      title: 'Common Mistakes',
      type: 'array',
      of: [defineArrayMember({type: 'string'})],
      description: 'Common compliance mistakes to avoid',
    }),
  ],
  preview: {
    select: {
      title: 'title',
      category: 'category',
      riskLevel: 'overallRiskLevel',
    },
    prepare({title, category, riskLevel}) {
      return {
        title,
        subtitle: `${category || 'Uncategorized'}${riskLevel ? ` - ${riskLevel.toUpperCase()} risk` : ''}`,
      }
    },
  },
})
