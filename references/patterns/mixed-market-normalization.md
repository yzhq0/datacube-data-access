# Mixed-Market Normalization

Read this file when live rows may mix A-share, Hong Kong, or other code families.

## Default rule

Inspect the observed runtime format before writing local filters, joins, or normalizers.

## Practical guidance

- do not assume every `con_code` is A-share
- normalize Hong Kong codes early, but use the live table format rather than assumed padding
- align date-column names before joins, for example `trade_date` vs `date`
- validate key uniqueness on the real downstream key such as `(con_code, trade_date)`

## Known source-specific defaults

Start from these defaults before you re-explore a familiar table family:

- DataCube native A-share, fund, and index tables usually use Tushare-style suffixed codes such as `000001.SZ`, `510300.SH`, and `000300.SH`
- Wind-mounted A-share quote and moneyflow tables commonly return the same suffixed style in rows
- Wind index-weight interfaces can require raw index-code inputs such as `000300` rather than `000300.SH`
- Wind Hong Kong quote tables can use unpadded HK codes such as `0700.HK`, `2892.HK`, and `80700.HK`
- Wind commodity and futures tables can use venue-style identifiers such as `Au9999.SGE`

## Known example

- Wind `hk_shareeodprices` used formats such as `0700.HK`, `2892.HK`, and `80700.HK`
- do not assume padded forms such as `00700.HK` unless the live rows actually use them
