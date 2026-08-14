#!/usr/bin/env python3
"""
sepa_to_wise.py — pretvornik SEPA pain.001.001.03 XML v Wise batch CSV.

Namen:
  Vzame plačilni XML (plače + davki/prispevki + računi dobaviteljev),
  izvožen iz računovodskega programa (npr. Minimax), in ga pretvori v CSV,
  ki ga je mogoče naložiti v Wise kot paketno plačilo (batch payment).

Izhodni format:
  Wise predloga "Send to bank accounts" (Send-to-bank-accounts.csv), varianta
  za NOVEGA prejemnika (10 stolpcev, s stolpcem IBAN). To NI predloga
  "All recipients" (ta ima recipientId/recipientDetail za obstoječe prejemnike).

Bistveno:
  Obvezni slovenski sklic (referenca z modelom SIxx) pri plačilu davkov se
  zapiše v ločeni STRUKTURIRANI stolpec `referenceNumber` — brez presledkov
  in brez dodatnega besedila, kot zahteva FURS. Prosto besedilo (opis) gre
  v `paymentReference`.

Avtor / kontakt:
  Egor Zyryanov, Setronica d.o.o. — contact@setronica.si

Uporaba:
  python3 sepa_to_wise.py vhod.xml [izhod.csv]
  python3 sepa_to_wise.py datoteka1.xml datoteka2.xml

Opombe:
  * Wise predloga za NOVEGA prejemnika ima 10 stolpcev:
    name, recipientEmail, paymentReference, referenceNumber, receiverType,
    amountCurrency, amount, sourceCurrency, targetCurrency, IBAN
  * amountCurrency = "target" — prejemnik dobi točen znesek (InstdAmt).
  * receiverType se določi po Purp in imenu (imena so diakritiko-neodvisna).

Mapiranje SEPA XML (CdtTrfTxInf) -> Wise CSV
--------------------------------------------
Zgradba enega plačila v XML:
  PmtInf/CdtTrfTxInf
    Amt/InstdAmt (Ccy="EUR")              -> znesek in valuta
    Cdtr/Nm                               -> ime prejemnika
    CdtrAcct/Id/IBAN                      -> IBAN
    Purp/Cd                               -> koda namena (za ugibanje tipa)
    RmtInf/Strd/CdtrRefInf/Ref            -> sklic / referenca (strukturirano)
    RmtInf/Strd/AddtlRmtInf               -> prosto besedilo (opis)
  (EndToEndId, ChrgBr, CdtrAgt/BIC, PstlAdr — se NE uporabljajo)

  Wise stolpec       Vir v XML                              Vrsta
  -----------------  -------------------------------------  ----------------
  name               Cdtr/Nm                                neposredno (whitespace)
  recipientEmail     — (ni v XML)                           vedno prazno
  paymentReference   Ref ali AddtlRmtInf (odvisno od tipa)  IZRAČUNANO (glej build_references)
  referenceNumber    CdtrRefInf/Ref                         neposredno (strukturiran sklic)
  receiverType       — (ni v XML)                           IZRAČUNANO (glej receiver_type)
  amountCurrency     — (konstanta)                          vedno "target"
  amount             Amt/InstdAmt                           neposredno
  sourceCurrency     Amt/InstdAmt/@Ccy                      neposredno
  targetCurrency     Amt/InstdAmt/@Ccy                      neposredno
  IBAN               CdtrAcct/Id/IBAN                       neposredno

Izračunani polji (ni neposredne kopije enega taga):
  * receiverType  — v SEPA XML ni polja fizična/pravna oseba. Ugibamo iz Purp/Cd
                    in besedila imena (glej receiver_type()).
  * paymentReference / referenceNumber — oba izhajata iz RmtInf/Strd
                    (Ref = sklic, AddtlRmtInf = opis). Razporeditev v build_references().
"""

import csv
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

# ---- Razvrstitev vrste prejemnika -------------------------------------------
BUSINESS_PURP = {"TAXS", "SUPP", "VATX", "GOVT", "SSBE", "LBRI"}
PERSON_PURP = {"SALA", "PRCP", "REFU", "BONU", "PENS"}
# Znaki podjetja/institucije v imenu (primerjamo na obliki BREZ diakritike):
BUSINESS_NAME_RE = re.compile(
    r"\b(d\.?o\.?o\.?|d\.?d\.?|s\.?p\.?|PODRACUN|PRORACUN|ZZZS|ZPIZ|FURS|"
    r"DAVCNI|ACCOUNTING|d\.n\.o\.|k\.d\.)\b",
    re.IGNORECASE,
)

# Slovenski model sklica: SI<2 številki>(<preostanek>). Preostanek je lahko
# prazen (npr. "SI99" = brez sklica).
SI_STRUCTURED_RE = re.compile(r"^SI(\d{2})(.*)$")
# ISO 11649 kreditna referenca (realna, ne kratek nadomestek kot 'RF040'):
RF_STRUCTURED_RE = re.compile(r"^RF\d{2}.{3,}$")
# Model 19 = davki/prispevki (FURS: sklic brez besedila in brez presledkov).
TAX_MODELS = {"19"}


def fold(s: str) -> str:
    """Odstrani diakritiko: 'PODRAČUN' -> 'PODRACUN'."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)
    )


def strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def find(el, path):
    cur = [el]
    for part in path.split("/"):
        nxt = []
        for node in cur:
            nxt.extend(c for c in node if strip_ns(c.tag) == part)
        cur = nxt
        if not cur:
            return None
    return cur[0]


def text(el, path, default=""):
    node = find(el, path)
    return node.text.strip() if node is not None and node.text else default


def build_references(ref: str, addtl: str):
    """
    Vrne (paymentReference, referenceNumber, je_davcni_sklic).

    - Vsak SI-sklic (SI19 davek, SI00 račun, SI99 "brez sklica", ...):
        referenceNumber = Ref  — čist strukturiran sklic (brez presledkov),
        paymentReference = AddtlRmtInf — Minimax ga zapiše kot "<sklic> <opis>"
          (sklic spredaj brez presledkov, opis za njim), kar je skladno s FURS.
      Če AddtlRmtInf ni, uporabimo Ref. Tako OBA polja nosita sklic (ne vemo,
      katero Wise posreduje naprej), opis pa ostane ohranjen.
    - Realen RF sklic (RF + kontrolni + številka): referenceNumber = Ref,
      paymentReference = opis.
    - Nadomestek 'RF040' / prazno / drugo: referenceNumber = "",
      paymentReference = opis (npr. 'Placa (7/26) ...').
    """
    ref = (ref or "").strip()
    addtl = (addtl or "").strip()

    m = SI_STRUCTURED_RE.match(ref)
    if m:
        # num = čist sklic; pay = AddtlRmtInf ("<sklic> <opis>"), sicer Ref.
        return (addtl or ref), ref, (m.group(1) in TAX_MODELS)

    if RF_STRUCTURED_RE.match(ref):        # realen RF (ne kratek 'RF040')
        return addtl, ref, False

    # RF040 / prazno / drugo — ni strukturiranega sklica.
    return (addtl or ref), "", False


def receiver_type(name: str, purp: str) -> str:
    purp = (purp or "").upper()
    if purp in BUSINESS_PURP:
        return "BUSINESS"
    if BUSINESS_NAME_RE.search(fold(name)):
        return "BUSINESS"
    if purp in PERSON_PURP:
        return "PERSON"
    return "PERSON"


FIELDS = [
    "name", "recipientEmail", "paymentReference", "referenceNumber", "receiverType",
    "amountCurrency", "amount", "sourceCurrency", "targetCurrency", "IBAN",
]


def convert(xml_path: Path):
    tree = ET.parse(xml_path)
    root = tree.getroot()

    rows, sklici = [], []
    total = 0.0

    for pmtinf in root.iter():
        if strip_ns(pmtinf.tag) != "PmtInf":
            continue
        for tx in pmtinf:
            if strip_ns(tx.tag) != "CdtTrfTxInf":
                continue

            name = re.sub(r"\s+", " ", text(tx, "Cdtr/Nm")).strip()
            iban = text(tx, "CdtrAcct/Id/IBAN").replace(" ", "")
            amt_node = find(tx, "Amt/InstdAmt")
            amount = amt_node.text.strip() if amt_node is not None else "0"
            ccy = (amt_node.get("Ccy") if amt_node is not None else "EUR") or "EUR"
            purp = text(tx, "Purp/Cd")
            ref = text(tx, "RmtInf/Strd/CdtrRefInf/Ref")
            addtl = text(tx, "RmtInf/Strd/AddtlRmtInf")

            pay_ref, ref_num, is_tax = build_references(ref, addtl)
            rtype = receiver_type(name, purp)

            rows.append({
                "name": name,
                "recipientEmail": "",
                "paymentReference": pay_ref,
                "referenceNumber": ref_num,
                "receiverType": rtype,
                "amountCurrency": "target",
                "amount": amount,
                "sourceCurrency": ccy,
                "targetCurrency": ccy,
                "IBAN": iban,
            })
            try:
                total += float(amount)
            except ValueError:
                pass
            if is_tax:
                sklici.append(f"  {name}: {ref_num}")

    ctrl = None
    for el in root.iter():
        if strip_ns(el.tag) == "CtrlSum" and el.text:
            ctrl = el.text.strip()
            break

    return rows, sklici, total, ctrl


def write_csv(rows, out_path: Path):
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("-")]
    if not args:
        print(__doc__)
        return 1

    explicit_out = None
    if len(args) == 2 and args[1].lower().endswith(".csv"):
        explicit_out = Path(args[1])
        args = args[:1]

    for xml_arg in args:
        xml_path = Path(xml_arg)
        if not xml_path.exists():
            print(f"NAPAKA: datoteka ni najdena — {xml_path}", file=sys.stderr)
            continue

        rows, sklici, total, ctrl = convert(xml_path)
        out_path = explicit_out or xml_path.with_name(xml_path.stem + "-wise.csv")
        write_csv(rows, out_path)

        print(f"\n{xml_path.name} -> {out_path.name}")
        cur = rows[0]["sourceCurrency"] if rows else ""
        print(f"  plačil: {len(rows)}   vsota: {total:.2f} {cur}")
        if ctrl is not None:
            ok = abs(total - float(ctrl)) < 0.005
            print(f"  CtrlSum:  {ctrl}   {'✓ ujema se' if ok else '✗ ODSTOPANJE!'}")
        for i, r in enumerate(rows, 1):
            if not r["IBAN"]:
                print(f"  ⚠ vrstica {i} ({r['name']}): prazen IBAN")
        if sklici:
            print("  Davčni sklici (model 19) → stolpec referenceNumber, brez presledkov:")
            print("\n".join(sklici))

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
