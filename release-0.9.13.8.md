# Boban 0.9.13.8 – Heureka CATEGORYTEXT + DELIVERY_DATE

- CATEGORYTEXT inherited from Woo parent for variants and expanded to full available Woo taxonomy path. This is NOT automatic translation to Heureka taxonomy.
- Merchant user can explicitly confirm a project-wide days-to-dispatch fallback (0–30). Without confirmation nothing is fabricated. Item-level dispatch days override fallback when present.
- ITEMGROUP_ID only for apparel/footwear size-only variants; no grouping for equipment/bikes.
- EAN preserved exactly as supplied; missing variant EAN is not copied from parent.
- Existing Google Merchant, shop account, feed URL/token, cached Woo catalog, selection and cron preserved.
- Existing database receives idempotent optional column default_delivery_days. Back up DB before deployment.
- Product feed must be republished manually in E-commerce after choosing trustworthy setting.
- Heureka account approval is independent from feed formatting.
- Avoid project-wide shipping fallback if supplier lead times vary. This release does not yet have supplier-specific configuration UI or automatic Heureka category taxonomy mapping.
