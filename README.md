# EU AI Act Compliance: Data Pipeline Instrumentation

This directory contains a complete implementation of EU AI Act compliance tooling for PySpark data pipelines, featuring automatic lineage tracking, AI-powered compliance analysis, and data governance report generation.

## Overview

The system consists of two example pipelines that demonstrate how data lineage flows across pipeline boundaries, along with the compliance infrastructure that tracks, analyzes, and documents transformations for regulatory compliance.

## Architecture

```
Pipeline 1 → /tmp/lineage → Compliance Analysis → /tmp/all_lineage (enriched)
                                                          ↓
Pipeline 2 → /tmp/lineage → Compliance Analysis → /tmp/all_lineage (enriched)
    ↑                                                     ↓
    └─────────── reads from Pipeline 1 ──────────────────┘
                 (lineage metadata flows forward)
```

## Pipeline Relationship

### Pipeline 1 (`pipeline1.py`)
**Purpose**: Initial data processing
**Input**: Creates sample user behavioral data (clicks, impressions, region, age)
**Transformation**: Calculates Click-Through Rate (CTR) = clicks / impressions
**Output**: `/tmp/pipeline1_output.csv`

### Pipeline 2 (`pipeline2.py`)
**Purpose**: Secondary processing using Pipeline 1's output
**Input**: Reads `/tmp/pipeline1_output.csv`
**Transformation**: Segments users into value tiers based on CTR
**Output**: `/tmp/pipeline2_output.csv`

**Key Relationship**: Pipeline 2 reads the output of Pipeline 1, demonstrating how lineage metadata flows across pipeline boundaries. When Pipeline 2 is analyzed, it inherits the origin and transformation metadata from Pipeline 1's data.

## Lineage Tracking with `lineage_spark`

### What is `lineage_spark`?

`lineage_spark` is a transparent instrumentation layer for PySpark that automatically tracks:
- **Row-level lineage**: Complete transformation history for each row
- **Data hashes**: SHA256 hashes for deduplication and linking
- **Input-output relationships**: Which input rows produced which output rows

### How It Works

1. **Import Interception**: Instead of importing from `pyspark.sql`, import from `lineage_spark.sql`:
   ```python
   from lineage_spark.sql import SparkSession  # instead of pyspark.sql
   from lineage_spark.sql.functions import col   # instead of pyspark.sql.functions
   ```

2. **Automatic Tracking**: Every `withColumn()` operation is automatically instrumented to record:
   - Operation type (`withColumn`)
   - Transformation expression (e.g., `/(clicks, impressions)`)
   - Input row hash (hash before transformation)
   - Output row hash (hash after transformation)

3. **Transparent Operation**: Your pipeline code remains unchanged - lineage tracking is completely transparent.

### Example Lineage Record

For a single row after `df.withColumn("ctr", col("clicks") / col("impressions"))`:

```json
{
  "data": {
    "user_id": 1,
    "clicks": 50,
    "impressions": 1000,
    "region": "US",
    "age": 25,
    "ctr": 0.05
  },
  "hash": "abc123...",
  "input_data_hash": "def456...",
  "lineage_chain": [
    {
      "op": "withColumn",
      "expr": "/(clicks, impressions)"
    }
  ]
}
```

## Lineage Persistence Flow

### Stage 1: Initial Persistence to `/tmp/lineage`

When a pipeline completes, lineage is automatically persisted to `/tmp/lineage`:

1. **Automatic Hook Trigger**: When `.toPandas()`, `.show()`, or other actions are called, `lineage_spark` triggers a post-persist hook
2. **Write to `/tmp/lineage`**: Raw lineage records (without enrichment) are written as JSONL files
3. **Deduplication**: Rows with duplicate hashes are skipped to avoid redundant analysis

**Files created**: `/tmp/lineage/part-{uuid}.jsonl`

### Stage 2: Compliance Analysis & Enrichment

The compliance analysis process enriches lineage with human-verified metadata:

```
/tmp/lineage → compliance_monitor.py → compliance_analyzer.py
                                              ↓
                                    Interactive Analysis
                                    (Requirements 1, 2, 3)
                                              ↓
                                    Enriched Records
```

#### Enrichment Process

**Requirement 1: Data Origin & Collection**
- AI analyzes where data came from and why it was collected
- Human provides clarification/confirmation
- Result: `data_origin_metadata` field added to each record

**Requirement 2: Transformation Lineage**
- AI categorizes transformation sequences (enrichment, aggregation, etc.)
- Human clarifies transformation purposes
- Result: `lineage_chain_metadata` field added to each record

**Requirement 3: Bias Analysis** (optional, for governance reports)
- AI examines dataset for potential biases
- Human confirms or corrects bias findings
- Result: Dataset-level `bias_metadata`

#### Example Enriched Record

```json
{
  "data": {"user_id": 1, "clicks": 50, "ctr": 0.05, ...},
  "hash": "abc123...",
  "input_data_hash": "def456...",
  "lineage_chain": [{"op": "withColumn", "expr": "/(clicks, impressions)"}],
  "data_origin_metadata": "Sample user behavioral data collected for CTR analysis demo",
  "lineage_chain_metadata": "Purpose: Calculate Click-Through Rate. Category: enrichment."
}
```

### Stage 3: Flush to `/tmp/all_lineage`

After enrichment, records are written to `/tmp/all_lineage` (historical lineage):

```
Enriched Records → /tmp/all_lineage/enriched_{timestamp}.jsonl
```

**Purpose**:
- Serves as historical record of all analyzed data
- Enables metadata propagation across pipeline boundaries
- Prevents re-analysis of data that's already been processed

## Compliance Analysis Components

### `compliance_monitor.py`
**Role**: Automatic trigger for compliance analysis
**When**: Called by `lineage_spark` hooks after pipeline completion
**What**: Checks if new lineage exists in `/tmp/lineage` and triggers analysis

### `compliance_analyzer.py`
**Role**: Interactive AI-powered compliance analysis
**Process**:
1. Loads lineage from `/tmp/lineage`
2. Presents data to GPT-4 for EU AI Act requirements analysis
3. Asks human clarifying questions
4. Extracts structured metadata from conversations
5. Enriches records with metadata
6. Optionally generates data governance report

## Data Governance Report Generation

During compliance analysis, you'll be asked:

```
Would you like to generate a data governance report? (yes/no):
```

If you choose **yes**:

1. **Bias Analysis (Requirement 3)** runs on the enriched dataset
2. AI examines data origins, transformations, and potential biases
3. Human provides feedback on bias findings
4. **AI generates comprehensive report** combining:
   - Data origin and collection metadata
   - Complete transformation lineage (including historical)
   - Dataset-level bias analysis

### Report Contents

The AI-generated report (`/tmp/data_governance_report_{timestamp}.json`) includes:

```json
{
  "report_type": "EU AI Act Data Governance Report",
  "generated_at": "2026-01-19T...",
  "data_origin_and_collection": {
    "summary": "...",
    "assessment": "..."
  },
  "transformation_lineage": {
    "summary": "...",
    "assessment": "..."
  },
  "bias_analysis": {
    "summary": "...",
    "recommendations": [...]
  }
}
```

## Usage

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set OpenAI API Key

```bash
export OPENAI_API_KEY='sk-...'
```

### 3. Run Pipeline 1

```bash
python pipeline1.py
```

**What happens**:
- Creates sample data, calculates CTR
- Lineage automatically tracked
- Written to `/tmp/lineage`
- Compliance analysis triggered automatically
- Interactive Q&A about data origin and transformations
- Enriched records written to `/tmp/all_lineage`

### 4. Run Pipeline 2

```bash
python pipeline2.py
```

**What happens**:
- Reads Pipeline 1 output
- Creates value tier based on CTR
- New lineage tracked in `/tmp/lineage`
- Compliance analysis triggered
- **Inherits metadata from Pipeline 1**
- Combined lineage metadata: "CTR calculation → User segmentation"
- Enriched records appended to `/tmp/all_lineage`

Runs both pipelines sequentially with full compliance analysis.