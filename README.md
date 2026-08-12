# SEPA credit transfer → Wise

Convert a SEPA **pain.001.001.03** payment file (salaries + taxes/contributions +
supplier invoices) into a **Wise batch-payment CSV** — while preserving the
mandatory Slovenian payment reference (`sklic`) that tax payments require.

There are two ways to use it, sharing identical logic:

- **[`index.html`](./index.html)** — a single-file web tool. Runs
  entirely in your browser: the XML never leaves your computer, nothing is
  uploaded or stored. Open it locally or host it on GitHub Pages.
- **[`sepa_to_wise.py`](./sepa_to_wise.py)** — a command-line script (Python 3,
  standard library only) for batch/automated use.

---

## Why

Wise lets you upload payments in bulk via CSV, but its template
(`name, recipientEmail, paymentReference, receiverType, amountCurrency, amount,
sourceCurrency, targetCurrency, IBAN`) doesn't match what accounting software
exports. Accounting programs produce ISO 20022 SEPA XML instead.

The tricky part: Slovenian payments to the state budget
(`PREHODNI DAVČNI PODRAČUN`, ZZZS, ZPIZ, FURS) **must** carry the structured
reference with its model, e.g. `SI19 31631053-40002`. Drop it and the payment
can't be allocated. This tool carries that `sklic` into Wise's `paymentReference`
field.

## Usage

### Browser (no install)

Open `index.html`, drop in your `.xml`, review the table, download the CSV.
Everything is client-side.

### Command line

```bash
python3 sepa_to_wise.py input.xml              # → input-wise.csv
python3 sepa_to_wise.py input.xml output.csv   # custom output name
python3 sepa_to_wise.py file1.xml file2.xml    # several files at once
```

No dependencies beyond Python 3.9+.

## How fields are mapped

| Wise column       | Source in SEPA XML                                   |
|-------------------|-----------------------------------------------------|
| `name`            | `Cdtr/Nm` (collapsed whitespace)                    |
| `paymentReference`| see **Reference** below                             |
| `receiverType`    | derived — see **Receiver type** below               |
| `amountCurrency`  | always `target` (recipient gets the exact amount)   |
| `amount`          | `Amt/InstdAmt`                                       |
| `sourceCurrency` / `targetCurrency` | `InstdAmt/@Ccy` (e.g. EUR)         |
| `IBAN`            | `CdtrAcct/Id/IBAN`                                   |
| `recipientEmail`  | left empty                                          |

### Reference (`sklic`)

- If the SEPA reference is a Slovenian model (`SI00`, `SI11`, `SI19`, …) it is
  **kept** and formatted as `SIxx <number>` — this is the mandatory tax `sklic`.
- Otherwise (e.g. salary lines whose reference is a placeholder like `RF040`) the
  human-readable purpose text (`AddtlRmtInf`, e.g. `Placa (6/26) …`) is used.

### Receiver type

- `BUSINESS` if the purpose code (`Purp/Cd`) is `TAXS`, `SUPP`, `VATX`, `GOVT`,
  `SSBE`, **or** the name matches a company/institution pattern
  (`d.o.o.`, `PODRAČUN`, `ZZZS`, `ZPIZ`, `FURS`, …).
- `PERSON` for `SALA`, `PRCP`, `REFU`, `BONU`, `PENS` and by default.

## Verification

Both versions sum all `InstdAmt` values and compare against `GrpHdr/CtrlSum`,
flagging any mismatch. The CLI also warns on empty IBAN / empty reference rows.

## ⚠️ Important limitations

- **Tax `sklic` travels as unstructured text.** Wise sends the reference in the
  unstructured remittance field, but the Slovenian tax system expects it in the
  *structured* field (model + reference). The value is preserved, but for reliable
  allocation, **pay taxes and contributions through a Slovenian bank** rather than
  Wise. The tool prints a warning for every such payment.
- **IBANs are copied as-is from the XML.** The tool does not validate them against
  invoices or a registry. If an IBAN in the export is outdated, Wise's
  *Verification of Payee* may reject the row — check recipient details separately.
- Company recipients must be entered as **Business** in Wise (names with digits,
  e.g. `GP 90, d.o.o.`, are rejected under the Person type).

## Privacy

The web tool is fully client-side — no backend, no analytics, no storage. Safe to
host as a static page (e.g. GitHub Pages) or run offline by saving the HTML file.
Do not add third-party scripts (analytics, trackers) if you self-host: keep payment
data in the browser only.

## License

MIT (suggested) — add a `LICENSE` file if you want to make reuse terms explicit.
