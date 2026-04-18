# Industry Classification

Read this file when the task involves any of these:

- industry classification for stocks or funds
- Shenwan or other industry-code mapping
- joins from a security table to an industry dictionary
- industry hierarchy rollups such as level 1, 2, or 3 aggregation

## Shared rule

For Wind stock-industry classification, the general pattern is the same across Shenwan and CITICS:

- classification table: security-to-industry membership
- dictionary table: `a_share_Industriescode`
- the classification code is compact
- the dictionary `code` is longer and zero-padded
- do not join on raw full-code equality

Use prefix normalization first, then join to the dictionary.

Observed hierarchy rule:

- first 4 characters identify the level-1 industry
- first 6 characters identify the level-2 industry
- first 8 characters identify the level-3 industry

Observed dictionary rule:

- `a_share_Industriescode` is the dictionary source
- `levelnum` is shifted by `+1` relative to the visible hierarchy level
- actual level-1 industry -> `levelnum = 2`
- actual level-2 industry -> `levelnum = 3`
- actual level-3 industry -> `levelnum = 4`

## Join discipline

- normalize to the intended hierarchy depth first, then map to the dictionary row
- if the task wants level-1, level-2, or level-3 aggregation, build the join key from the corresponding prefix length instead of trimming after the join
- keep the hierarchy-level rule explicit in the result so downstream users know whether the output is level 1, 2, or 3
- document the prefix-length rule in your query or transformation output rather than assuming the next task will rediscover it

## Shenwan example

- classification table: `a_share_swindustriesclass`
- compact code field: `sw_ind_code`
- validate whether `sw_ind_code` is actually accepted as a selective server-side filter before you depend on it in extraction logic

Observed example:

- level-1 industry `交通运输`
- `a_share_swindustriesclass.sw_ind_code`: `760d010200`
- level-1 prefix `760d` -> dictionary code `760d000000000000`
- level-2 prefix `760d01` -> `物流`
- level-3 prefix `760d0102` -> `中间产品及消费品供应链服务`

## CITICS example

- classification table: `ashare_ind_class_citics`
- compact code field: `citics_ind_code`

Observed example:

- `ashare_ind_class_citics.citics_ind_code`: `b104020100`
- level-1 prefix `b104` -> dictionary code `b104000000000000`, industry `电力及公用事业`
- level-2 prefix `b10402` -> dictionary code `b104020000000000`, industry `环保及公用事业`
- level-3 prefix `b1040201` -> dictionary code `b104020100000000`, industry `环保`
