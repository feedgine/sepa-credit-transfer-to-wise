#!/usr/bin/env python3
"""
sepa_to_wise.py — pretvornik SEPA pain.001.001.03 XML v Wise batch CSV.

Namen:
  Vzame plačilni XML (plače + davki/prispevki + računi dobaviteljev),
  izvožen iz računovodskega programa, in ga pretvori v CSV, ki ga je
  mogoče naložiti v Wise kot paketno plačilo (batch payment).

Bistveno:
  Obvezni slovenski sklic (referenca z modelom SIxx) pri plačilu davkov
  se ohrani v polju paymentReference — brez njega plačila v proračun
  ni mogoče razporediti.

Uporaba:
  python3 sepa_to_wise.py vhod.xml [izhod.csv]
  # če izhod.csv ni podan, se ime tvori samodejno: <vhod>-wise.csv

  # več datotek naenkrat:
  python3 sepa_to_wise.py datoteka1.xml datoteka2.xml

Opombe:
  * amountCurrency = "target" — prejemnik dobi točen znesek (InstdAmt).
  * receiverType se določi po namenski kodi (Purp) in imenu prejemnika.
  * Wise pošlje referenco kot NESTRUKTURIRANO polje remittance.
    Slovenska davčna običajno pričakuje sklic v strukturiranem polju,
    zato je davčna plačila varneje izvesti prek slovenske banke.
    Skripta izpiše opozorilo za vsako tako plačilo.
"""

import csv
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# ---- Razvrstitev vrste prejemnika -------------------------------------------
# Purp kode, ki nedvoumno pomenijo podjetje/institucijo:
BUSINESS_PURP = {"TAXS", "SUPP", "VATX", "GOVT", "SSBE"}
# Purp kode fizičnih oseb (plača, nadomestila, povračila):
PERSON_PURP = {"SALA", "PRCP", "REFU", "BONU", "PENS"}
# Znaki podjetja/institucije v imenu prejemnika:
BUSINESS_NAME_RE = re.compile(
    r"\b(d\.?o\.?o\.?|d\.?d\.?|s\.?p\.?|PODRACUN|PRORACUN|ZZZS|ZPIZ|FURS|"
    r"DAVCNI|ACCOUNTING|d\.n\.o\.|k\.d\.)\b",
    re.IGNORECASE,
)

# Model slovenskega sklica: SI + 2 številki (SI00, SI11, SI19, SI99, ...).
SI_MODEL_RE = re.compile(r"^SI\d{2}")


def strip_ns(tag: str) -> str:
    """Odstrani namespace: '{urn:...}Nm' -> 'Nm'."""
    return tag.split("}", 1)[-1] if "}" in tag else tag


def find(el, path):
    """Iskanje po lokalnih imenih oznak, brez upoštevanja namespace."""
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


def format_reference(ref: str, addtl: str) -> tuple[str, bool]:
    """
    Vrne (referenca_za_Wise, je_obvezen_sklic).

    Če je ref slovenski model SIxx (sklic za davke/račune) — ga ohranimo
    kot 'SIxx preostanek' (obvezni sklic). Sicer vzamemo besedilni opis
    (AddtlRmtInf), če ga ni pa sam ref.
    """
    ref = (ref or "").strip()
    addtl = (addtl or "").strip()
    if SI_MODEL_RE.match(ref):
        model, rest = ref[:4], ref[4:]
        formatted = f"{model} {rest}".strip()
        return formatted, True
    # RF040 in podobni kratki nadomestki ne nosijo koristne informacije —
    # zato imamo raje človeku berljiv namen plačila.
    if addtl:
        return addtl, False
    return ref, False


def receiver_type(name: str, purp: str) -> str:
    purp = (purp or "").upper()
    if purp in BUSINESS_PURP:
        return "BUSINESS"
    if BUSINESS_NAME_RE.search(name or ""):
        return "BUSINESS"
    if purp in PERSON_PURP:
        return "PERSON"
    # Privzeto — PERSON (varneje za plačilne datoteke plač).
    return "PERSON"


def convert(xml_path: Path):
    tree = ET.parse(xml_path)
    root = tree.getroot()

    rows = []
    warnings = []
    total = 0.0

    for pmtinf in root.iter():
        if strip_ns(pmtinf.tag) != "PmtInf":
            continue
        for tx in pmtinf:
            if strip_ns(tx.tag) != "CdtTrfTxInf":
                continue

            name = text(tx, "Cdtr/Nm")
            name = re.sub(r"\s+", " ", name).strip()  # odstrani dvojne presledke
            iban = text(tx, "CdtrAcct/Id/IBAN").replace(" ", "")
            amt_node = find(tx, "Amt/InstdAmt")
            amount = amt_node.text.strip() if amt_node is not None else "0"
            ccy = (amt_node.get("Ccy") if amt_node is not None else "EUR") or "EUR"
            purp = text(tx, "Purp/Cd")
            ref = text(tx, "RmtInf/Strd/CdtrRefInf/Ref")
            addtl = text(tx, "RmtInf/Strd/AddtlRmtInf")

            reference, mandatory = format_reference(ref, addtl)
            rtype = receiver_type(name, purp)

            rows.append(
                {
                    "name": name,
                    "recipientEmail": "",
                    "paymentReference": reference,
                    "receiverType": rtype,
                    "amountCurrency": "target",
                    "amount": amount,
                    "sourceCurrency": ccy,
                    "targetCurrency": ccy,
                    "IBAN": iban,
                }
            )
            try:
                total += float(amount)
            except ValueError:
                pass

            if mandatory:
                warnings.append(
                    f"  [sklic] {name}: referenca '{reference}' — "
                    f"obvezni davčni sklic se prenaša kot nestrukturirano besedilo"
                )

    # Kontrolna vsota iz GrpHdr, če obstaja.
    ctrl = None
    for el in root.iter():
        if strip_ns(el.tag) == "CtrlSum" and el.text:
            ctrl = el.text.strip()
            break

    return rows, warnings, total, ctrl


FIELDS = [
    "name", "recipientEmail", "paymentReference", "receiverType",
    "amountCurrency", "amount", "sourceCurrency", "targetCurrency", "IBAN",
]


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

    # Če sta natanko dva argumenta in se drugi konča na .csv — je to izhod.
    explicit_out = None
    if len(args) == 2 and args[1].lower().endswith(".csv"):
        explicit_out = Path(args[1])
        args = args[:1]

    for xml_arg in args:
        xml_path = Path(xml_arg)
        if not xml_path.exists():
            print(f"NAPAKA: datoteka ni najdena — {xml_path}", file=sys.stderr)
            continue

        rows, warnings, total, ctrl = convert(xml_path)
        out_path = explicit_out or xml_path.with_name(xml_path.stem + "-wise.csv")
        write_csv(rows, out_path)

        print(f"\n{xml_path.name} -> {out_path.name}")
        print(f"  plačil: {len(rows)}   vsota: {total:.2f} {rows[0]['sourceCurrency'] if rows else ''}")
        if ctrl is not None:
            ok = abs(total - float(ctrl)) < 0.005
            print(f"  CtrlSum:  {ctrl}   {'✓ ujema se' if ok else '✗ ODSTOPANJE!'}")
        # Vrstice brez IBAN ali brez reference — možne težave.
        for i, r in enumerate(rows, 1):
            if not r["IBAN"]:
                print(f"  ⚠ vrstica {i} ({r['name']}): prazen IBAN")
            if not r["paymentReference"]:
                print(f"  ⚠ vrstica {i} ({r['name']}): prazna referenca")
        if warnings:
            print("  Pozor — davčni sklici (preverite razporeditev / plačajte prek slovenske banke):")
            print("\n".join(warnings))

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
