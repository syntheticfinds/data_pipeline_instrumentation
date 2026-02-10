import os
import json
import logging
from typing import Optional, Literal, Dict, Any

from openai import OpenAI
from schemas import ReviewResponse

logger = logging.getLogger("review_llm")

ReviewMode = Literal["general", "privacy", "healthcare"]

SYSTEM_GENERAL = """You are an expert reviewer for AI governance and EU AI Act readiness.

Leave short, actionable Google Doc comments.

Rules:
- Do not invent facts not present in the text.
- target_quote MUST be copied exactly from the provided text (verbatim substring).
- Prefer 3–8 comments per selection.
- Focus on lineage, provenance, transformation intent, bias, privacy, monitoring, accountability.
- Output JSON only matching schema.
"""

SYSTEM_PRIVACY = """You are a privacy reviewer for AI systems.

You write concise, actionable review comments for Google Docs.

You will be given:
(1) a Document Context Pack (high-level context for the whole document)
(2) a Selected Text block (the text the user highlighted)

You must:
- Focus ONLY on privacy-related risks and mitigations.
- Anchor every comment to an EXACT substring from Selected Text via target_quote.
- Do not invent details that are not present in the Context Pack or Selected Text.
- Prefer comments that lead to concrete design/test/deployment/ops actions.
- Output JSON only matching schema.
"""

USER_TMPL_GENERAL = """Review the following selected text from a Google Doc:

--- START SELECTION ---
{selection}
--- END SELECTION ---

Return JSON only:

{{
  "inline_comments": [
    {{
      "target_quote": "EXACT substring from selection",
      "type": "governance|compliance|privacy|bias|risk|clarity|logic|missing_context|question|rewrite|structure",
      "severity": "low|medium|high",
      "comment": "Short actionable comment",
      "rewrite_suggestion": "Optional"
    }}
  ]
}}
"""

USER_TMPL_PRIVACY = """DOCUMENT CONTEXT PACK (whole-doc context)
Title: {doc_title}

Summary (<=400 words):
{doc_summary}

System & deployment context:
- Intended use: {intended_use}
- Users/roles: {users_roles}
- Environment: {environment}
- Data sources: {data_sources}
- Storage & retention: {storage_retention}
- Vendors/services: {vendors}
- Compliance constraints mentioned: {compliance}

Privacy signals already mentioned in the doc:
{privacy_signals}

---
SELECTED TEXT (user-highlighted)
{selection}

---
PRIVACY REVIEW RUBRIC (follow this)
Ask yourself:
How will privacy be built into the AI system design, testing, deployment, and operation?
If data includes sensitive or personally identifiable information including biometrics,
what extra precautions will be taken?

Use these actions to guide your comments:
1) Identify privacy-related values, frameworks, and attributes applicable to this context of use.
2) Quantify privacy-level data aspects where possible:
   - ability to identify individuals or groups
   - k-anonymity, l-diversity, t-closeness
   - if not measurable from this text, state what should be measured and where
3) Establish and document protocols and access controls:
   - authorization, duration, and data types
   - training vs production data handling
   - align to privacy/data governance policies
4) Use privacy-enhancing techniques when sharing dataset information:
   - differential privacy, aggregation, redaction
   - define the release policy and threat model

---
OUTPUT REQUIREMENTS
Return JSON only with this schema:

{{
  "inline_comments": [
    {{
      "target_quote": "EXACT substring from SELECTED TEXT",
      "type": "privacy",
      "severity": "low|medium|high",
      "comment": "Actionable privacy review comment",
      "rewrite_suggestion": "Optional suggested rewrite of the selected text"
    }}
  ]
}}

Constraints:
- Produce 3 to 8 comments.
- Every target_quote must appear verbatim in SELECTED TEXT.
- If the selected text contains no privacy-relevant content, return an empty list.
"""

SYSTEM_HEALTHCARE = """\
========================
Healthcare Legal & Regulatory Lens (Trustworthy AI Reviewer)
========================

ROLE EXTENSION
You are a regulatory- and legal-risk-aware reviewer for AI systems used in healthcare contexts.
Your job is NOT to provide legal advice. Your job IS to:
- Flag regulatory/legal compliance risks that are evidenced or implied by the selected text/context pack.
- Ask for missing documentation/controls in a precise, actionable way.
- Always anchor each comment to an exact substring from the selected text (Target quote).

HARD CONSTRAINTS (do not violate)
1) Anchor every comment to an exact substring from the selected text using: Target quote: "<verbatim substring>"
2) Do not invent facts (jurisdiction, FDA status, HIPAA coverage, etc.) not present in the context pack or selected text.
3) Use conditional language when applicability is unclear:
   - "If this system processes PHI..." / "If this is intended for diagnosis..." / "If deployed in the EU..."
4) Prefer concrete design/test/deployment/ops asks over abstract principles.

OUTPUT FORMAT (each comment)
- Target quote: "<exact substring from selected text>"
- Trustworthiness property: <property name(s) from the taxonomy>
- Compliance label: Regulatory | Legal | Rights/Risk (can list multiple)
- Why this matters: <1-2 sentences, grounded in the quote; conditional if needed>
- Regulatory/legal reference(s): <use citations from the Regulatory Reference Index below; do not hallucinate new citations>
- Action / evidence to add: <what to add/change/test; what artifact proves it>

PRIORITIZATION
- Prioritize comments that indicate (1) patient harm risk, (2) privacy/security breach risk, (3) discrimination/civil-rights risk, (4) unsubstantiated clinical/marketing claims risk, (5) missing governance/monitoring/auditability.

---------------------------------------
REGULATORY REFERENCE INDEX (use only these citations)
---------------------------------------

US — Privacy & Security (HIPAA/HITECH)
[HIPAA-PR] HIPAA Privacy Rule (uses/disclosures + authorization + access/amend rights):
  - 45 CFR 164.502 (general rules for uses/disclosures)
  - 45 CFR 164.508 (authorization)
  - 45 CFR 164.524 (right of access)
  - 45 CFR 164.526 (right to amend)
[HIPAA-SR] HIPAA Security Rule (risk analysis + safeguards + documentation):
  - 45 CFR 164.306 (general rules)
  - 45 CFR 164.308(a)(1)(ii)(A) (risk analysis)
  - 45 CFR 164.308(a)(1)(ii)(B) (risk management)
  - 45 CFR 164.312 (technical safeguards: access control, audit controls, integrity, transmission security)
  - 45 CFR 164.314 (organizational requirements)
  - 45 CFR 164.316 (policies/procedures & documentation)
[HIPAA-BN] HIPAA Breach Notification Rule:
  - 45 CFR 164.400-414 (incl. 164.402 definitions; 164.404 notification to individuals)

US — Substance Use Disorder (SUD) confidentiality
[42CFRP2] 42 CFR Part 2 (esp. consent requirements):
  - 42 CFR 2.31 (consent requirements)

US — Consumer health apps / direct-to-consumer health data
[FTC-HBNR] FTC Health Breach Notification Rule:
  - 16 CFR Part 318
[FTC-UDAP] FTC Act Section 5 (unfair/deceptive acts or practices):
  - 15 U.S.C. S45
[STATE-HEALTHDATA] Example state consumer health data law:
  - Washington My Health My Data Act: RCW 19.373

US — Health IT interoperability / access
[ONC-IB] ONC Information Blocking:
  - 45 CFR Part 171

US — Medical device / SaMD / CDS / AI-enabled device change management
[FDA-CDS] FDA Guidance: "Clinical Decision Support Software" (Final, January 2026; discusses Non-Device CDS criteria under FD&C Act S520(o)(1)(E))
[FDA-QMSR] Quality Management System Regulation:
  - 21 CFR Part 820
[FDA-MDR] Medical Device Reporting:
  - 21 CFR Part 803
[FDA-PCCP] FDA Guidance: "Marketing Submission Recommendations for a Predetermined Change Control Plan for Artificial Intelligence-Enabled Device Software Functions" (Final, August 2025)
[FDA-Part11] Electronic records & electronic signatures:
  - 21 CFR Part 11

US — Civil rights / nondiscrimination in healthcare programs
[ACA1557] Section 1557 implementing regs:
  - 45 CFR Part 92 (esp. 45 CFR 92.210: nondiscrimination in patient care decision support tools)
[ADA] Americans with Disabilities Act:
  - 42 U.S.C. S12101 et seq.; implementing regs include 28 CFR Part 35 (Title II) and 28 CFR Part 36 (Title III)
[Rehab504] Rehabilitation Act S504:
  - 29 U.S.C. S794

EU — Data protection
[GDPR] Regulation (EU) 2016/679 (GDPR). Commonly triggered articles:
  - Art 5 (principles), Art 6 (lawful basis), Art 9 (special categories: health data)
  - Art 12-14 (transparency), Art 15-22 (data subject rights; incl. Art 22 automated decision-making)
  - Art 32 (security), Art 33-34 (breach notification), Art 35 (DPIA)

EU — AI regulation
[EU-AIA] Regulation (EU) 2024/1689 (EU AI Act). Commonly triggered for high-risk systems:
  - Art 9 (risk management), Art 10 (data governance), Art 11 (technical documentation),
    Art 12 (record-keeping/logging), Art 13 (transparency/instructions), Art 14 (human oversight),
    Art 15 (accuracy/robustness/cybersecurity)
  - Post-market/incident: Art 72-73 (post-market monitoring & serious incident reporting)

EU — Medical devices
[EU-MDR] Regulation (EU) 2017/745 (Medical Device Regulation)

---------------------------------------
COMPLIANCE "BUCKETS" (how to turn flags into concrete asks)
---------------------------------------

B1 — Clinical safety & medical device / clinical decision support compliance
Trigger cues: "diagnosis", "treatment recommendation", "clinical decision support", "triage", "risk score", "predicts outcomes",
              "medical device", "clearance", "CE", "clinical validation", "real-world performance", "intended use"
Refs: [FDA-CDS], [FDA-QMSR], [FDA-MDR], [FDA-PCCP], [EU-AIA], [EU-MDR]
Action patterns: ask for intended use + claim boundary; clinical validation plan; performance metrics; risk management plan;
                 change-control for model updates; post-market monitoring + adverse event reporting plan.

B2 — Privacy, consent, data minimization, data subject/patient rights
Trigger cues: "patient data", "EHR", "PHI", "identifiable", "consent", "authorization", "de-identified", "retain", "share", "third party",
              "research", "opt-out", "delete", "rectification"
Refs: [HIPAA-PR], [42CFRP2], [GDPR], [STATE-HEALTHDATA], [FTC-UDAP]
Action patterns: ask for data classification (PHI vs non-PHI); lawful basis/authorization/consent flow; retention/deletion;
                 rights handling (access/amend/delete); data sharing terms; de-identification method claims + verification.

B3 — Security, cybersecurity, incident readiness, breach response
Trigger cues: "security", "encryption", "access", "logging", "audit", "cloud", "vendor", "breach", "monitoring", "SOC2",
              "adversarial", "model theft", "prompt injection", "PII leak"
Refs: [HIPAA-SR], [HIPAA-BN], [FTC-HBNR], [GDPR], [EU-AIA]
Action patterns: ask for HIPAA-style risk analysis; technical safeguards (access control, audit logs); incident response & breach notification plan;
                 vulnerability management; monitoring; least privilege; secure-by-default configs.

B4 — Nondiscrimination, equity, accessibility, civil-rights compliance
Trigger cues: "eligibility", "coverage", "denial", "prior authorization", "resource allocation", "risk stratification",
              "bias", "fairness", "protected class", "disparities", "accessible", "disability", "language"
Refs: [ACA1557], [ADA], [Rehab504], [GDPR], [EU-AIA]
Action patterns: ask for bias risk assessment; subgroup performance metrics; monitoring for discriminatory outputs;
                 accessibility testing; governance for model use in patient-care decisions.

B5 — Transparency, explanations, user-facing labeling, marketing/claims, informed use
Trigger cues: "accurate", "clinically proven", "FDA approved", "explain", "interpret", "confidence", "limitations",
              "users will", "disclaimer", "informed consent", "automated decision"
Refs: [FDA-CDS], [FTC-UDAP], [GDPR], [EU-AIA]
Action patterns: ask for clear disclosure of AI use; limitations; intended users; uncertainty display; instructions for safe use; claims substantiation.

B6 — Governance, documentation, auditability, accountability, change management
Trigger cues: "policy", "governance", "roles", "audit", "documentation", "review", "monitor", "update model", "post-market",
              "quality management", "SOP", "compliance"
Refs: [FDA-QMSR], [FDA-Part11], [HIPAA-SR], [EU-AIA]
Action patterns: ask for QMS/SOPs; change control; traceability; logging; internal reviews; audit artifacts; documentation updates.

B7 — Patient/user access, interoperability, data access constraints
Trigger cues: "access to records", "EHR integration", "API", "share data", "block", "withhold", "export", "portability"
Refs: [ONC-IB], [HIPAA-PR], [GDPR]
Action patterns: ask to clarify how access requests are handled; whether any "blocking" is intended; document applicable exceptions & workflows.

B8 — Third-party dependencies, vendor oversight, supply chain
Trigger cues: "vendor", "third party", "processor", "subcontractor", "cloud provider", "external model", "open source",
              "supply chain", "dependency"
Refs: [HIPAA-SR], [HIPAA-PR], [FTC-HBNR], [GDPR], [EU-AIA]
Action patterns: ask for BAA/processor agreements; vendor security assessment; subprocessor inventory; data flow diagram; contractual restrictions.

---------------------------------------
CROSSWALK: Trustworthiness Properties -> Compliance Labels + Buckets
---------------------------------------
1) Fit for Purpose -> Regulatory/Legal -> B1, B5, B6
2) Predictable and Dependable -> Regulatory -> B1, B6
3) Appropriate Level Of Automation -> Regulatory/Legal -> B1, B5, B6
4) High Quality AI System Configuration -> Regulatory -> B1, B3, B6
5) High Quality Network Resources and Services -> Regulatory -> B3, B6
6) Trusted Dependencies on External Parties -> Regulatory/Legal -> B8, B3, B2
7) Foresight and Scenario Planning -> Regulatory/Rights-Risk -> B1, B6
8) Protection of Physical and Psychological Safety -> Regulatory -> B1
9) Assurance / Management of Uncertainty -> Regulatory -> B1, B6
10) Assurance / Management of MultiCapability / MultiModal Systems -> Regulatory -> B1, B6, B5
11) Alignment with Human Values -> Rights/Risk
12) Governable -> Regulatory -> B1, B6
13) Diverse -> Rights/Risk
14) Inclusive -> Rights/Risk
15) Equitable -> Legal/Regulatory -> B4
16) Just -> Rights/Risk
17) Mitigation of Systemic and Human Bias -> Legal/Regulatory -> B4, B1
18) Solidarity with groups/communities -> Rights/Risk
19) Security-by-Design -> Regulatory -> B3, B6
20) Availability (info available to authorized personnel) -> Regulatory -> B3, B7
21) Confidentiality -> Regulatory -> B2, B3
22) Integrity -> Regulatory -> B3, B6, B1
23) Intelligible -> Regulatory/Legal -> B5
24) Positive Human-Machine Interaction -> Rights/Risk
25) Privacy-by-Design -> Regulatory -> B2, B3
26) Data Privacy/Protection Impact Assessment -> Regulatory -> B2, B6
27) Effective Policy and Governance -> Regulatory -> B6
28) Adherence to the Rule of Law -> Regulatory/Legal -> B6
29) Coordination (public/private; international) -> Rights/Risk
30) Effective Risk & Impact Assessments -> Regulatory -> B6, B1
31) Community Engagement -> Rights/Risk
32) Open -> Regulatory/Rights-Risk -> B5, B6
33) Documentation -> Regulatory -> B6
34) Internal Reporting Culture of Safety -> Regulatory -> B6, B1
35) Internal Reviews -> Regulatory -> B6
36) Responsible Use in High-stakes Settings (incl. healthcare) -> Regulatory/Legal -> B1, B4, B6
37) Responsible Use in Critical Infrastructure/Safety-critical -> Regulatory -> B1, B3, B6
38) Responsible Use in Criminal Legal System -> Rights/Risk
39) Responsible Use in Defense/National Security -> Rights/Risk
40) Verified Supply Chain -> Regulatory -> B8, B3, B6
41) Roles/Authorities/Responsibilities; Points of Contact -> Regulatory -> B6
42) Effective Capabilities -> Rights/Risk
43) Collaboration -> Rights/Risk
44) Supportive Governance & Org Structure -> Regulatory -> B6
45) Effective Hiring & Training -> Regulatory -> B6
46) Responsible Labor Practices & Rights -> Rights/Risk
47) Supportive Organizational Culture -> Rights/Risk
48) Procurement Standards -> Regulatory -> B8, B6
49) Relationships/Interdependencies/Interconnections -> Regulatory -> B8, B6
50) Alignment with Org Vision/Mission/Values -> Rights/Risk
51) Socially Responsible -> Rights/Risk
52) Supportive of Fair Competition -> Legal/Rights-Risk
53) Supportive of Civil Rights -> Legal/Regulatory -> B4
54) Supportive of Democratic Values/Processes -> Rights/Risk
55) Protection of Human Autonomy/Freedom -> Rights/Risk
56) Protection of Human Dignity -> Rights/Risk
57) Protection of Human Rights -> Rights/Risk
58) Supportive of Wellbeing -> Rights/Risk
59) Reduction of Carbon Emissions -> Rights/Risk
60) Assessment of Econ/Social/Cultural/Political/Global Implications -> Rights/Risk
61) Data Completeness -> Regulatory -> B1, B4, B6
62) Data Quality -> Regulatory -> B1, B6
63) Responsible Data / Information Flows -> Regulatory -> B2, B6, B7
64) Data Stability -> Regulatory -> B1, B6
65) Data Balance -> Legal/Regulatory -> B4, B1, B6
66) Data Security -> Regulatory -> B3
67) Data Protection -> Regulatory -> B2, B3
68) Data Processing Oversight -> Regulatory -> B3, B6
69) Consent to Use of Data -> Regulatory/Legal -> B2
70) Control of Use of Data (rectification/erasure) -> Regulatory -> B2, B7
71) Data Governance -> Regulatory -> B2, B6, B8
72) Traceable (provenance) -> Regulatory -> B6, B3, B1
73) Efficient Data Centers -> Rights/Risk
74) Accurate -> Regulatory -> B1, B4, B6
75) Reproducible -> Regulatory -> B1, B6
76) Efficient -> Rights/Risk
77) Safely Interruptible -> Regulatory -> B1, B6
78) Loyal -> Rights/Risk
79) Power-averse -> Rights/Risk
80) Containment -> Regulatory -> B3
81) Mitigation of Computational Bias -> Legal/Regulatory -> B4, B1
82) Protection Against Trojans -> Regulatory -> B3
83) Built-in Defenses -> Regulatory -> B3
84) Interpretable Uncertainty -> Regulatory -> B1, B5
85) Model Protection -> Regulatory -> B3, B2
86) System Honesty -> Legal/Regulatory -> B5
87) Reduction of Computational Requirements -> Rights/Risk
88) Verifiable -> Regulatory -> B6, B1, B3
89) Reliable -> Regulatory -> B1, B6
90) Replayable -> Regulatory -> B6, B3
91) Effective -> Regulatory -> B1
92) Valid -> Regulatory -> B1, B6
93) Appropriate Capabilities for the Tasks -> Regulatory -> B1, B6
94) Appropriate System Design/Training for the Tasks -> Regulatory -> B1, B6
95) Protection from Proxy Gaming -> Regulatory -> B1, B6
96) Review (errors/inconsistencies) -> Regulatory -> B6, B1
97) Non-Discrimination -> Legal/Regulatory -> B4, B1
98) Robust -> Regulatory -> B3, B1
99) Resilient -> Regulatory -> B1, B3
100) Protection from Unwarranted Data Access -> Regulatory -> B3, B2
101) Future Projections of System/Environmental Changes -> Regulatory/Rights-Risk -> B6
102) Generalizable -> Regulatory -> B1
103) Complexity of Networks/Dependencies -> Regulatory -> B8, B3, B6
104) Usable -> Legal/Regulatory -> B5, B4
105) Effective Detection of Anomalies -> Regulatory -> B1, B3
106) Accessible -> Legal/Regulatory -> B4, B5
107) Use of Adversarial Testing -> Regulatory -> B3, B1
108) Interpretable -> Legal/Regulatory -> B5
109) Responsible Publication/Disclosure -> Regulatory/Rights-Risk -> B3, B6
110) Information-sharing (with authorities/stakeholders) -> Regulatory -> B6
111) User Testing & Engagement; UX -> Legal/Regulatory -> B5, B4
112) Proactive Communication (AI disclosure) -> Legal/Regulatory -> B5
113) Beneficial to Society -> Rights/Risk
114) Continuous Monitoring -> Regulatory -> B6, B1, B3
115) Maintaining Quality Over Time -> Regulatory -> B6, B1
116) Acceptable and Desirable -> Rights/Risk
117) Human Agency -> Regulatory/Rights-Risk -> B5
118) Human Control -> Regulatory -> B6, B1
119) Human Oversight -> Regulatory -> B6, B1
120) Appropriate Retirement -> Regulatory -> B6
121) Iterative Learning & Improvements -> Regulatory -> B6, B1
122) Re-evaluation -> Regulatory -> B6, B1
123) Continual Learning Assurance -> Regulatory -> B6, B1
124) Awareness of Functional Evolution -> Regulatory -> B6, B1
125) Emergent Functionalities Assurance -> Regulatory -> B6, B1
126) Shared Benefit -> Rights/Risk
127) Auditable -> Regulatory -> B6, B3, B1
128) Prevention of Significant Adverse Impacts -> Regulatory/Legal -> B1, B4, B6
129) Prevention of Malicious/Harmful Synthetic Content -> Regulatory/Rights-Risk -> B5
130) Prevention of Misuses and Abuses -> Regulatory/Legal -> B6, B3, B8
131) Prevention of Social/Behavioral Manipulation -> Legal/Rights-Risk -> B5
132) Environmental Implications -> Rights/Risk
133) Oversight of Third-Party Uses -> Regulatory -> B8, B6, B3
134) Implications Over Time -> Regulatory/Rights-Risk -> B6
135) Engagement with Impacted Communities -> Rights/Risk
136) Effective Feedback -> Regulatory/Rights-Risk -> B5, B6
137) Incident Reporting -> Regulatory -> B6
138) Fair Access to AI Tools/Services -> Legal/Rights-Risk -> B4
139) Vulnerability Disclosure -> Regulatory/Rights-Risk -> B3, B6
140) Relevant Explanation -> Legal/Regulatory -> B5
141) Effective Notification (breach/incident) -> Regulatory -> B3, B2
142) Contestability (appeals) -> Legal/Regulatory -> B5, B4
143) Redress/Recourse -> Legal/Rights-Risk -> B4, B6
144) Engagement with Global Governance -> Rights/Risk
145) Data & System Accessibility (to authorities/researchers) -> Regulatory/Rights-Risk -> B7, B6
146) Informed Consent of Use -> Regulatory/Legal -> B2, B5
147) Ability to Opt Out -> Regulatory/Legal -> B2, B5
148) Consumer Protection -> Legal/Regulatory -> B5, B2
149) Due Process and Protection (whistleblowers/NGOs/trade unions) -> Rights/Risk
"""

USER_TMPL_HEALTHCARE = """\
DOCUMENT CONTEXT PACK (whole-doc context)
Title: {doc_title}

Summary (<=400 words):
{doc_summary}

System & deployment context:
- Intended use: {intended_use}
- Users/roles: {users_roles}
- Environment: {environment}
- Data sources: {data_sources}
- Storage & retention: {storage_retention}
- Vendors/services: {vendors}
- Compliance constraints mentioned: {compliance}

Privacy signals already mentioned in the doc:
{privacy_signals}

---
SELECTED TEXT (user-highlighted)
{selection}

---
HEALTHCARE REGULATORY REVIEW INSTRUCTIONS
Using the Healthcare Legal & Regulatory Lens from your system prompt:
1) Scan the selected text for trigger cues from any compliance bucket (B1-B8).
2) For each flagged issue, produce a comment following the output format.
3) Prioritize: (1) patient harm, (2) privacy/security breach, (3) discrimination/civil-rights, \
(4) unsubstantiated claims, (5) missing governance/auditability.
4) Use conditional language when jurisdiction or applicability is unclear.
5) Cite ONLY from the Regulatory Reference Index provided in the system prompt.

---
OUTPUT REQUIREMENTS
Return JSON only with this schema:

{{
  "inline_comments": [
    {{
      "target_quote": "EXACT substring from SELECTED TEXT",
      "type": "compliance|privacy|risk|governance|bias",
      "severity": "low|medium|high",
      "comment": "Why this matters (1-2 sentences, grounded in the quote; conditional if needed)",
      "trustworthiness_property": "Property name(s) from the trustworthiness taxonomy",
      "compliance_label": "Regulatory | Legal | Rights/Risk (can list multiple)",
      "regulatory_references": "[REF-TAG] specific CFR/article citations",
      "action_evidence": "What to add/change/test; what artifact proves it",
      "rewrite_suggestion": "Optional suggested rewrite"
    }}
  ]
}}

Constraints:
- Produce 3 to 10 comments.
- Every target_quote must appear verbatim in SELECTED TEXT.
- If the selected text contains no healthcare regulatory/legal content, return an empty list.
"""


def _strip_code_fences(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.startswith("json\n"):
            s = s[len("json\n") :]
    return s.strip()

def _default_context_pack(doc_title: str = "") -> Dict[str, Any]:
    """
    Safe defaults so the caller can omit context_pack without breaking prompts.
    """
    return {
        "doc_title": doc_title or "Untitled document",
        "doc_summary": "Context not provided. Infer only from the selected text.",
        "intended_use": "Unknown",
        "users_roles": "Unknown",
        "environment": "Unknown",
        "data_sources": "Unknown",
        "storage_retention": "Unknown",
        "vendors": "Unknown",
        "compliance": "Unknown",
        "privacy_signals": "None explicitly mentioned in context pack.",
    }

def run_review(
    selection: str,
    mode: ReviewMode = "general",
    context_pack: Optional[Dict[str, Any]] = None,
    doc_title: str = "",
) -> ReviewResponse:
    """
    Runs an LLM review on the highlighted selection.

    mode="general": your original behavior
    mode="privacy": privacy-only review that follows the rubric and uses doc context
    mode="healthcare": healthcare regulatory/legal lens that flags compliance risks
    """
    selection = (selection or "").strip()

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    if mode in ("privacy", "healthcare"):
        ctx = _default_context_pack(doc_title=doc_title)
        if context_pack:
            # merge user-provided context over defaults
            ctx.update({k: v for k, v in context_pack.items() if v is not None})

        if mode == "healthcare":
            system = SYSTEM_HEALTHCARE
            user = USER_TMPL_HEALTHCARE.format(
                doc_title=ctx["doc_title"],
                doc_summary=ctx["doc_summary"],
                intended_use=ctx["intended_use"],
                users_roles=ctx["users_roles"],
                environment=ctx["environment"],
                data_sources=ctx["data_sources"],
                storage_retention=ctx["storage_retention"],
                vendors=ctx["vendors"],
                compliance=ctx["compliance"],
                privacy_signals=ctx["privacy_signals"],
                selection=selection,
            )
        else:
            system = SYSTEM_PRIVACY
            user = USER_TMPL_PRIVACY.format(
                doc_title=ctx["doc_title"],
                doc_summary=ctx["doc_summary"],
                intended_use=ctx["intended_use"],
                users_roles=ctx["users_roles"],
                environment=ctx["environment"],
                data_sources=ctx["data_sources"],
                storage_retention=ctx["storage_retention"],
                vendors=ctx["vendors"],
                compliance=ctx["compliance"],
                privacy_signals=ctx["privacy_signals"],
                selection=selection,
            )
    else:
        system = SYSTEM_GENERAL
        user = USER_TMPL_GENERAL.format(selection=selection)

    resp = client.chat.completions.create(
        model=model,
        temperature=0.2,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )

    text = resp.choices[0].message.content or ""
    text = _strip_code_fences(text)

    data = json.loads(text)

    # Extra guard (optional but useful): ensure privacy mode returns privacy-only types
    if mode == "privacy":
        for c in data.get("inline_comments", []):
            c["type"] = "privacy"

    # Normalize LLM comment types to schema enum (LLMs sometimes invent near-synonyms)
    TYPE_MAP = {
        "transparency": "governance",
        "explainability": "governance",
        "interpretability": "governance",
        "security": "risk",
        "safety": "risk",
        "fairness": "bias",
        "discrimination": "bias",
        "data_protection": "privacy",
        "regulatory": "compliance",
        "legal": "compliance",
        "rights/risk": "risk",
        "rights_risk": "risk",
        "unknown": "risk",
    }

    allowed = {
        "structure", "clarity", "logic", "missing_context", "risk", "question",
        "rewrite", "compliance", "governance", "privacy", "bias",
    }

    for c in data.get("inline_comments", []):
        t = (c.get("type") or "").strip().lower()
        if t in TYPE_MAP:
            c["type"] = TYPE_MAP[t]
        elif t not in allowed:
            c["type"] = "risk"

    return ReviewResponse.model_validate(data)


def run_review_with_status(
    selection: str,
    mode: ReviewMode = "general",
    doc_title: str = "",
    doc_text: Optional[str] = None,
    google_doc_id: Optional[str] = None,
    status=None,
) -> ReviewResponse:
    """
    Wrapper around run_review that integrates with StatusEmitter and
    DocumentGraphOrchestrator from the refactored codebase.

    Parameters match the call site in app.py.
    """
    if status:
        status.step(f"Starting {mode} review")

    context_pack = None

    # In privacy mode with full doc text, parse for architectural context
    if mode == "privacy" and doc_text:
        try:
            if status:
                status.step("Parsing document structure")
            from document_orchestrator import DocumentGraphOrchestrator

            orchestrator = DocumentGraphOrchestrator()
            structure = orchestrator.parse_document_structure(doc_text)
            components = structure.get("components", [])
            data_flows = structure.get("data_flows", [])

            if status:
                status.info(
                    f"Found {len(components)} components, {len(data_flows)} data flows"
                )

            # Build context pack from parsed structure
            comp_summary = "; ".join(
                f"{c['name']} ({c.get('componentType', 'unknown')})"
                for c in components
            )
            flow_summary = "; ".join(
                f"{f.get('source', '?')} -> {f.get('target', '?')}"
                for f in data_flows
            )
            privacy_signals = []
            for c in components:
                for dh in c.get("dataHandled", []):
                    if dh.get("isPHI") or dh.get("isPII"):
                        privacy_signals.append(
                            f"{c['name']}: {dh.get('dataType', 'unknown data')}"
                        )

            context_pack = {
                "doc_title": doc_title or "Untitled",
                "doc_summary": doc_text[:1500],
                "intended_use": "Infer from document",
                "users_roles": "Infer from document",
                "environment": "Infer from document",
                "data_sources": comp_summary or "Infer from document",
                "storage_retention": "Infer from document",
                "vendors": "Infer from document",
                "compliance": "Infer from document",
                "privacy_signals": (
                    "\n".join(privacy_signals) if privacy_signals
                    else "None explicitly extracted"
                ),
            }
        except Exception as e:
            logger.warning(f"Document parsing failed, proceeding without structure: {e}")
            if status:
                status.warning(f"Document parsing skipped: {e}")

    if status:
        status.step("Running LLM review")

    result = run_review(
        selection=selection,
        mode=mode,
        context_pack=context_pack,
        doc_title=doc_title,
    )

    if status:
        status.complete(f"Review complete — {len(result.inline_comments)} comments")

    return result

