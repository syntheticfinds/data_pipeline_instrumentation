import {hipaaPart} from './hipaaPart'
import {hipaaSubpart} from './hipaaSubpart'
import {hipaaRegulation} from './hipaaRegulation'
import {aiComplianceScenario} from './aiComplianceScenario'

// Document graph types for design document analysis
import {designDocument} from './designDocument'
import {documentSection} from './documentSection'
import {technicalComponent} from './technicalComponent'
import {dataFlow} from './dataFlow'
import {complianceIssue} from './complianceIssue'
import {modificationSuggestion} from './modificationSuggestion'

export const schemaTypes = [
  // HIPAA regulation schemas
  hipaaPart,
  hipaaSubpart,
  hipaaRegulation,
  aiComplianceScenario,

  // Document graph schemas
  designDocument,
  documentSection,
  technicalComponent,
  dataFlow,
  complianceIssue,
  modificationSuggestion,
]
