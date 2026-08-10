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

## Financial and tender islands

These are extracted into plain tables (financials, trial_balance, receivables,
assets, ledger, bank, ra_bills, final_bills, boq, bonds, compliance, iso_certs,
dossiers) rather than through the observation model, because no independent
second document restates a ledger line -- there is nothing to corroborate
against. Where an internal check exists we assert it instead:

- ledger/bank: every row confirmed against the running balance it states.
  95.5% of ledger rows and 99.2% of bank rows confirmed; the rest are REPORTED
  as unresolved, never guessed (they straddle page breaks).
- RA bills: work done + GST 18% - retention = net claimed, closes on 6/6.
- final bills: as-executed BOQ total equals stated billed value, 6/6.
- BOQ: quantity x rate = amount on 49/49 lines.
- financial statements: PBT - tax = PAT on 7/7.

Neither island bridges to a named work. Contract numbers and RFP numbers are
separate identifier spaces; contract #70 belongs to a different client than
work "... Pkg-70", so the obvious join is demonstrably wrong. Not bridged.

Data quality: 32 of 60 performance bonds guarantee zero rupees and all six
dossiers state zero earnest money. Do not aggregate those fields.

## Layout

    src/        extractors, one per document family + common.py
    data/       generated observation and table files
    notebooks/  exploration

## Run

    pip install -r requirements.txt
    python src/company_cert.py ../BITS-Hackathon-Dataset
