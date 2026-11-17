# Salesforce Retail POS T-log samples: fit with our standard POS model

Date: 2026-11-17. Source: the 9 POSLog XML samples on Salesforce's "Export the Transaction Log (TLog)" page
(CheckoutOrder, CheckoutPromotion, PriceOverride, TransactionDiscount, FullReturn, PartialReturn, ExchangeEven,
ExchangeChargeMore, ExchangeRefundDue). Synthetic vendor examples, not a customer feed.

## What we ran

1. Each file went through our current POSLog 6.0 template (`retail/daab/crosswalks/poslog-6.0.yaml`) with the same parser the
   production worker uses, offline. **All 9 were rejected at the first step (`missing_id_part`)**: the template expects
   `BusinessUnit/UnitID` + `RetailTransaction`, and Salesforce sends neither. Salesforce is a different POSLog *dialect*.
2. We then wrote a **prototype Salesforce template** (`salesforce-pos-poslog`, mapping only, no code change) and ran the same
   9 files through it. **All 9 load with 0 rejects**, and all 4 reconciliation checks pass on every file (lines = gross,
   gross − discount = net, net + tax = tenders paid). The template also passes the DAAB template validation and loads in a
   local DAAB. Customer e-mail and address are read as "not stored", so they are neither saved nor kept as sample values.

| Sample | Lines | Gross | Discount | Net | Tax | Paid (tenders) |
|---|---|---|---|---|---|---|
| CheckoutOrder | 2 | 448.00 | 0 | 448.00 | 58.24 | 506.24 |
| CheckoutPromotion | 2 | 54.00 | 11.60 | 42.40 | 5.51 | 47.91 |
| PriceOverride (+1 price_override row, reason 001) | 1 | 8.80 | 1.32 | 7.48 | 0.97 | 8.45 |
| TransactionDiscount | 2 | 13.60 | 2.72 | 10.88 | 1.42 | 12.30 |
| ExchangeChargeMore / Even / RefundDue | 1 each | 6.90 / 9.20 / 6.70 | 0 | same | 0.90 / 1.20 / 0.87 | 7.80 / 10.40 / 7.57 |
| FullReturn / PartialReturn (sale part only) | 2 each | 16.60 / 38.00 | 0 | same | 2.16 / 4.94 | 18.76 / 42.94 |

This is the point of the standard model: a new POS dialect is a new mapping file, and the same metrics and reports run on it.
The table below is the field-by-field fit.

## Have / Partial / Missing

| Area | Status | Salesforce sample | Note |
|---|---|---|---|
| Transaction id | Have | `TransactionID` (order #, e.g. US00001055) | `SequenceNumber` is always 1, not usable as id |
| Store | Partial | `WorkstationID` = store id (per Salesforce's notes), `TillID` = register | No `BusinessUnit/UnitID`; mapping must swap the fields |
| Business date / time | Partial | `BusinessDayDate` `2020-08-28Z`, `BeginDateTime` in UTC (`...Z`) | Date has a `Z` suffix; times are UTC, so the store's time zone is needed to get the local business day |
| Sale status / type | Have | `CustomerOrderTransaction@TransactionStatus` = RETAIL_AUTH or RETAIL_SALE (both = completed sale) | Enum mapping only |
| Training flag | Have | `Transaction@TrainingModeFlag` | |
| Cashier | Partial | `OperatorID@AssociateID` (attribute, not text); item-level `AssociateID` | Item-level sales attribution is extra (we can keep it) |
| Sale lines | Have | `Sale/Item`: ItemID, Quantity, RegularSalesUnitPrice, ActualSalesUnitPrice, ExtendedAmount, DiscountAmount | Fields are nested one level deeper (`Sale/Item/...`) than our template expects |
| Line amount basis | Partial | `ExtendedAmount` is **after** discount in every discounted sample (Promotion 38.00 − 10.00 = 28.00; PriceOverride 8.80 − 1.32 = 7.48; GeneralDiscount 6.90 − 1.38 = 5.52) | Ours is before discount; mapping must use unit price × quantity or we would subtract the discount twice. `ActualSalesUnitPrice` stays at list price in the samples although Salesforce's note says it is after discount: to confirm on real data |
| Product id / barcode | Have | `ItemID`, `POSIdentity@POSIDType=GTIN` | |
| Line tax | Have | `Sale/Tax[@LineItemTotalTax='true']/Amount` + per-tax breakdown (type, rate) | |
| Order tax | Have | separate `LineItem/Tax` with taxable amount and tax | |
| Transaction totals | Partial | no `Total` elements | Derived from lines, the order tax line and tenders in the prototype; the "paid = net + tax" check passes on all 9 |
| Tender | Have | `Tender@TenderType`, `Amount`, `CreditDebit@CardType`, auth reference | Cash change not shown in samples |
| Promotion | Have | `RetailPriceModifier MethodCode=Promotion`, `PromotionID`, `MerchantPromotionId` | Maps to our hosted-promo (TPR) savings |
| Price override | Have | `RetailPriceModifier MethodCode=PriceOverride`, `Amount Action=Subtract`, `ReasonCode` | No approving manager |
| Transaction discount | Have | `RetailPriceModifier MethodCode=GeneralDiscount` + `Discount ProratedFlag=true` | Already prorated to lines |
| Sign convention | Partial | all amounts positive in samples; subtraction via `Action="Subtract"` | No negative-amount example; returns would confirm |
| Returns (full / partial) | Missing | the return samples contain only the original sale order | Salesforce says a return is a separate "Return of Old Transaction" file, and return detail is in the JSON `orderActivityLog` (`returnProductList`). Need a real return XML |
| Original sale link | Missing | not in samples | Needed for "refund without receipt" and refund-vs-original checks |
| Exchanges | Partial | Documented: `IsExchange` flag, two files per exchange (new sale + return of old), one transaction id spans both orders | The 3 exchange samples show only the new sale and carry no `IsExchange`; need both files of one exchange to confirm the link |
| Line void / cancel / post-void | Missing | not in samples | Salesforce documents voided carts on a separate page; need samples |
| Manager override / supervisor | Missing | not in samples | |
| No-sale / drawer / cashier events | Missing | not in samples | Would need an electronic-journal feed (mark unavailable, not zero) |
| Currency | Partial | `CurrencyCode` (USD, CAD) | We assume one currency per project |
| Customer | Present, not used | `CustomerID`, e-mail address | Personal data: we would drop it at mapping, not store it |

Note: the published samples carry Salesforce's explanations inline (`-- Store ID`, ...). A real export would not; we strip
them for testing.

## What it would take

1. **Sales, promotions, price overrides, discounts, tax and tenders: done as a prototype** (above). Hardening it on one real
   store day (codes, edge cases, tests): about 1 day. Same pipeline and replay protection as upload.
2. **One small parser change**: `BusinessDayDate` arrives as `2020-08-28Z`, which our date parser rejects. The prototype uses
   the UTC date of `BeginDateTime` instead, which can be the wrong local business day for evening sales. Accepting the `Z`
   form (or converting UTC to the store time zone) is about 0.5 day.
3. **Returns, exchanges, voids**: blocked until we have real samples (return XML of an old transaction, both files of one
   exchange, a voided cart). With those, about 1-2 days more.
4. Not mapped in the prototype: the transaction-level `Discount` element (the same amount is already prorated into the
   lines' `DiscountAmount`, so totals are right), per-tax breakdown (type, rate), card brand.

We will only finish a vendor template once the target retailer's POS is confirmed; the Salesforce one stays a prototype.

## Needed from the retailer / Salesforce

- One day of real exports for one store, including at least one return, one exchange and one voided cart.
- Store time zone, and confirmation that `WorkstationID` is the store id in their setup.
- Their tender, reason and promotion code lists.
- Whether they use SFTP (XML) or the webhook (JSON). The JSON has return detail the XML samples do not show.
