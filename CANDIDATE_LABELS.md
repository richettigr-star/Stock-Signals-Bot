# Candidate labels, not a new strategy

New daily ENTRY events now distinguish `new` from `revalidated`: a revalidation
means the same symbol had a prior-day pending, unconfirmed recommendation when
the new closed-session scan was accepted. It does not mean a second purchase.
Confirmed holdings remain separate and are never relabelled as entry candidates.

The ranking, universe, allocation, event IDs, expiry, delivery deduplication and
stop rules are unchanged. Historical events without classification are explicitly
labelled as such, not retrospectively called new. No historical alert is resent.

The change is applied to future daily scans. A current pending recommendation
is not a holding without the user's manual confirmation. Passing offline tests
does not imply future signal quality or guaranteed availability.
