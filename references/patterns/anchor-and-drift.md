# Anchor-And-Drift

Read this file when only monthly official weights are available and the workflow needs daily estimated weights between anchors.

## Drift model

Let the latest official anchor date be `tau`.

- official anchor weight: `w_i,tau`
- daily constituent return: `r_i,s`
- drifted raw weight: `raw_w_i,t = w_i,tau * product(1 + r_i,s)`
- normalized estimate: `w_hat_i,t = raw_w_i,t / sum_j raw_w_j,t`

## Implementation details

- prefer adjusted prices or adjusted return fields when available
- use the previous trading day's drifted weight with today's moneyflow to reduce same-day leakage
- re-normalize within the live constituent universe every estimated day
- if a constituent is missing quote history after the anchor, exclude it and record the coverage loss

## Error evaluation

Validate the estimate against the next official snapshot:

1. take the official month-end weights at `tau`
2. drift them to the next official snapshot date
3. compare the estimate with the next official weights

Useful metrics:

- `mae_union`
- `max_abs_error`
- top-holding overlap metrics when relevant
- coverage metrics for quote and moneyflow support

Low drift error does not guarantee good downstream moneyflow quality when constituent coverage is incomplete.
