# JAW 2026 Hackathon — Bid Intelligence

Multi-hop numerical QA over a 687-document construction corpus.

## Approach

Not RAG. Documents are extracted **once** into a structured knowledge base;
questions are then answered by querying that KB. Retrieval cannot answer
these questions because the evidence is semantically dissimilar to the query,
because aggregates need a complete set rather than top-k, and because absence
questions ("how many works have no reference letter") cannot be answered from
retrieved documents.

## Observation model

Extractors do not write field values directly. Each emits **observations**:

    {subject, field, value, source, extractor}

one row per fact-as-stated-by-one-document. The works table is *derived* from
these. Because most facts are stated by 2-3 independent documents, source
disagreement is a query, not a silent overwrite -- and agreement is our
correctness evidence.

## Verified so far

- 155/155 works extracted from company completion certificates, no gaps
- total value INR 5,530.4 Cr, matching the corpus README
- 28 distinct clients (the README's "62" is not reproducible from documents)
- defect-liability check: completion + 365 days matches the stated end date
  on 80/80 long-family certificates -- confirms dd/mm/yyyy parsing
- past-performance portfolio agrees with certificates on 152/152 values

## Known gaps

- contract number (RA bills, BOQ workbooks) does not map to a named work.
  Contract #70's client differs from Pkg-70's client -- the numbering spaces
  are unrelated. Not bridged; do not guess.
- RFP number (bonds, compliance matrices, dossiers) appears in no certificate.
- 14 works have no client sector tag; fill by propagating from the same
  client's other certificates, not by inferring from the name.

## Layout

    src/        extractors, one per document family + common.py
    data/       generated observation and table files
    notebooks/  exploration

## Run

    pip install -r requirements.txt
    python src/company_cert.py ../BITS-Hackathon-Dataset
