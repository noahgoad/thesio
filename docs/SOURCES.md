# Data sources

## SEC company information

The company directory and Company Facts workflow uses fixed public SEC endpoints. Company name, ticker and CIK bindings are checked; usable financial facts retain unit, reporting-period and source context.

Network access is not guaranteed. Fair-access restrictions and HTTP errors are surfaced rather than hidden behind fabricated facts. Operators should set an appropriate application/contact User-Agent.

Retained SEC response bodies remain local. The public repository includes code and synthetic fixtures, not development captures or original filing bodies.

## Authorized documents

Users may supply documents they are entitled to process. Registration preserves source bytes, hashes and quote offsets. Filing import separates raw and extracted-text digests. A URL label does not cause an arbitrary network fetch.

Hash equality establishes internal consistency, not document authenticity, publication history, accounting correctness or redistribution rights.

## Synthetic examples

The guided AI-spending example and regression fixtures are synthetic and labeled accordingly. Support/challenge labels are annotations. These fixtures do not establish real company performance or a causal relationship.

## Research boundaries

A missing value stays missing. Different periods and units must be reconciled before comparison. A structured financial observation does not independently establish a causal claim. Saved conclusions are the user's assessment, not source certification.

See [REUSE](REUSE.md) for conceptual reference attribution.
