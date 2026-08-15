# SEPA credit transfer → Wise

Convert a SEPA **pain.001.001.03** payment file (salaries + taxes/contributions +
supplier invoices), e.g. exported from Minimax, into a **Wise batch-payment CSV** —
carrying the mandatory Slovenian payment reference (`sklic`) into Wise's structured
`referenceNumber` column exactly as FURS requires.

Two ways to use it, sharing identical logic:

- **[`index.html`](./index.html)** — a single-file web tool. Runs entirely in your
  browser: the XML never leaves your computer, nothing is uploaded or stored. Open
  it locally or host it on GitHub Pages.
- **[`sepa_to_wise.py`](./sepa_to_wise.py)** — a command-line script (Python 3,
  standard library only) for batch/automated use.

Live tool: `https://feedgine.github.io/sepa-credit-transfer-to-wise/`

---

## Output format — Wise "Send to bank accounts" (new recipient, 10 columns)

The output matches Wise's **Send-to-bank-accounts.csv** template (the new-recipient
variant that includes an `IBAN` column). It is **not** the "All recipients" template
(which uses `recipientId` / `recipientDetail` for already-saved recipients).

```
name,recipientEmail,paymentReference,referenceNumber,receiverType,amountCurrency,amount,sourceCurrency,targetCurrency,IBAN
```

| Column            | Source / rule                                                        |
|-------------------|----------------------------------------------------------------------|
| `name`            | `Cdtr/Nm` (collapsed whitespace)                                     |
| `paymentReference`| free-text description; empty for tax rows (see below)                |
| `referenceNumber` | **structured** reference / `sklic`, verbatim, no spaces             |
| `receiverType`    | `BUSINESS` / `PERSON` — see below                                    |
| `amountCurrency`  | always `target` (recipient gets the exact amount)                   |
| `amount`          | `Amt/InstdAmt`                                                       |
| `sourceCurrency` / `targetCurrency` | `InstdAmt/@Ccy` (e.g. EUR)                         |
| `IBAN`            | `CdtrAcct/Id/IBAN`                                                   |
| `recipientEmail`  | left empty                                                          |

### Reference handling (`sklic`)

The Slovenian tax authority (FURS) requires the tax reference **without spaces and
without extra text**, in the dedicated reference field. So:

- **Any SI reference** (SI19 tax, SI00 invoice, SI99 "no reference", …):
  `referenceNumber` = the clean structured reference from `Ref` (no spaces), and
  `paymentReference` = `AddtlRmtInf`. Minimax writes `AddtlRmtInf` as
  `<reference> <description>` — the reference first (no internal spaces) with any
  text after it — which is exactly the form FURS permits. This way **both** fields
  carry the reference (we don't know which one Wise forwards to the Slovenian
  banking system), while the human description is preserved. If `AddtlRmtInf` is
  empty, `Ref` is used.
- **Real RF reference** (RF + check digits + number) → `referenceNumber` gets it,
  `paymentReference` keeps the description.
- **Placeholder `RF040` / none** → `referenceNumber` empty, `paymentReference`
  gets the description.

> FURS guidance (paraphrased): the reference must be written as e.g.
> `SI1948539619-44008`, with no extra text and no spaces; if text is unavoidable it
> must go *after* the reference, never before it.

### Receiver type

- `BUSINESS` if the purpose code (`Purp/Cd`) is `TAXS`, `SUPP`, `VATX`, `GOVT`,
  `SSBE`, `LBRI`, **or** the name matches a company/institution pattern
  (`d.o.o.`, `PODRAČUN`, `ZZZS`, `ZPIZ`, `FURS`, …). Name matching is
  **diacritic-insensitive**, so `PODRAČUN` and `PODRACUN` both match.
- `PERSON` for `SALA`, `PRCP`, `REFU`, `BONU`, `PENS` and by default.

## Usage

### Browser (no install)

Open `index.html`, drop in your `.xml`, review the table, download the CSV.

### Command line

```bash
python3 sepa_to_wise.py input.xml              # → input-wise.csv
python3 sepa_to_wise.py input.xml output.csv   # custom output name
python3 sepa_to_wise.py file1.xml file2.xml    # several files at once
```

No dependencies beyond Python 3.9+.

## Verification

Both versions sum all `InstdAmt` values and compare against `GrpHdr/CtrlSum`,
flagging any mismatch, and list the tax references written to `referenceNumber`.

## ⚠️ Notes & limitations

- **IBANs are copied as-is from the XML.** They are not validated against invoices
  or a registry. If an IBAN in the export is outdated, Wise's *Verification of Payee*
  may reject the row — check recipient details separately.
- Company recipients are exported as **Business** (names with digits, e.g.
  `GP 90, d.o.o.`, are rejected under the Person type in Wise).
- **`name` and `paymentReference` are transliterated to ASCII** (č→c, ž→z, š→s, …)
  so the output stays within the SEPA-safe basic Latin (SWIFT) character set;
  diacritics are outside the guaranteed SEPA set and may be altered downstream. The
  `sklic` in `referenceNumber` is already ASCII and is left untouched. Other text
  (e.g. double spaces from the accounting program) is otherwise preserved.

## Privacy

The web tool is fully client-side — no backend, no analytics, no storage. Safe to
host as a static page (GitHub Pages) or run offline by saving the HTML file. Do not
add third-party scripts (analytics, trackers) if you self-host.

## Maintainer

Egor Zyryanov, **Setronica d.o.o.** — contact@setronica.si
[Pravno obvestilo](https://setronica.si/pravno-obvestilo/) ·
[Pogoji varstva osebnih podatkov](https://setronica.si/pogoji-varstva-osebnih-podatkov/) ·
[Politika piškotkov](https://setronica.si/politika-piskotkov/)

## License

[MIT](./LICENSE) — © 2026 Setronica d.o.o. Free and open source.
