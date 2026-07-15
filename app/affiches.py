"""Génération d'affiches promotionnelles prêtes à imprimer, destinée à
remplacer PNR. Import du tableau de suivi des promotions existant (CSV,
colonnes habituelles + 4 ajoutées à la main par le siège : Gabarit, Message
affiche, Format, Date debut/fin), aperçu instantané, publication vers les
points de vente. Module en évaluation le 2026-07-15 (voir garde-fou sur
config.DEFAULT_STORE_CODE dans main.py) — pas encore ouvert aux vrais points
de vente au-delà du magasin par défaut."""

import csv
import io
import re
from calendar import monthrange
from datetime import date, datetime
from io import BytesIO

from jinja2 import Environment
from pypdf import PdfReader, PdfWriter
from sqlalchemy.orm import Session
from weasyprint import HTML

from .models import AFFICHE_GABARITS, AfficheProduit

MOIS_FR = {
    "janv": 1, "fevr": 2, "févr": 2, "mars": 3, "avr": 4, "mai": 5, "juin": 6,
    "juil": 7, "aout": 8, "août": 8, "sept": 9, "oct": 10, "nov": 11, "dec": 12, "déc": 12,
}
MONTH_ROW_RE = re.compile(r"^([a-zéû]{3,4})[.\-/](\d{2,4})$", re.IGNORECASE)


def parse_month_row(first_cell: str):
    m = MONTH_ROW_RE.match(first_cell.strip().lower())
    if not m:
        return None
    mois_txt, annee_txt = m.groups()
    mois_num = MOIS_FR.get(mois_txt)
    if not mois_num:
        return None
    annee = int(annee_txt)
    if annee < 100:
        annee += 2000
    return annee, mois_num


def parse_french_price(value: str):
    if not value:
        return None
    cleaned = re.sub(r"[^0-9,.\-]", "", value).replace(",", ".")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_date_field(value: str, fallback: date):
    if not value or not value.strip():
        return fallback
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return fallback


def read_csv_text(raw_bytes: bytes) -> str:
    for encoding in ("cp1252", "latin-1", "utf-8"):
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="replace")


def import_affiches_csv(db: Session, raw_bytes: bytes) -> dict:
    """Importe le tableau de suivi. Ne crée une AfficheProduit que pour les
    lignes où la colonne 'Gabarit' a été remplie par le siège. Remplace les
    lignes non publiées des mois rencontrés (un import = l'état de référence
    du mois pour ce qui n'est pas déjà diffusé)."""
    text = read_csv_text(raw_bytes)
    reader = csv.DictReader(io.StringIO(text), delimiter=";")

    current_annee, current_mois_num = None, None
    mois_touches = set()
    a_creer = []
    lignes_ignorees = 0

    for row in reader:
        first_key = reader.fieldnames[0]
        first_cell = (row.get(first_key) or "").strip()

        month_match = parse_month_row(first_cell)
        if month_match and not (row.get("PRODUIT") or "").strip():
            current_annee, current_mois_num = month_match
            continue

        gabarit = (row.get("Gabarit") or "").strip().lower()
        if not gabarit:
            continue
        if gabarit not in AFFICHE_GABARITS:
            lignes_ignorees += 1
            continue
        if current_annee is None:
            lignes_ignorees += 1
            continue

        cip = (row.get(first_key) or "").strip()
        produit = (row.get("PRODUIT") or "").strip()
        if not cip or not produit:
            lignes_ignorees += 1
            continue

        mois_str = f"{current_annee:04d}-{current_mois_num:02d}"
        mois_touches.add(mois_str)
        debut_defaut = date(current_annee, current_mois_num, 1)
        fin_defaut = date(current_annee, current_mois_num, monthrange(current_annee, current_mois_num)[1])

        a_creer.append(dict(
            mois=mois_str,
            cip=cip,
            produit=produit,
            labo=(row.get("LABO.") or "").strip(),
            prix_ttc=parse_french_price(row.get("PV TTC") or row.get("PV LOC") or ""),
            message_affiche=(row.get("Message affiche") or "").strip(),
            gabarit=gabarit,
            format=(row.get("Format") or "A4").strip().upper() or "A4",
            date_debut=parse_date_field(row.get("Date debut") or row.get("Date début") or "", debut_defaut),
            date_fin=parse_date_field(row.get("Date fin") or "", fin_defaut),
        ))

    for mois_str in mois_touches:
        db.query(AfficheProduit).filter(AfficheProduit.mois == mois_str, AfficheProduit.published.is_(False)).delete()

    for data in a_creer:
        db.add(AfficheProduit(**data))

    db.commit()
    return {"importees": len(a_creer), "ignorees": lignes_ignorees, "mois": sorted(mois_touches)}


def render_affiche_html(jinja_env: Environment, affiche: AfficheProduit) -> str:
    template = jinja_env.get_template(f"gabarits/{affiche.gabarit}.html")
    return template.render(promotion=affiche)


def render_affiche_pdf_bytes(jinja_env: Environment, affiche: AfficheProduit) -> bytes:
    html = render_affiche_html(jinja_env, affiche)
    return HTML(string=html).write_pdf()


def merge_affiches_pdf(jinja_env: Environment, affiches: list[AfficheProduit]) -> bytes:
    writer = PdfWriter()
    for affiche in affiches:
        pdf_bytes = render_affiche_pdf_bytes(jinja_env, affiche)
        reader = PdfReader(BytesIO(pdf_bytes))
        for page in reader.pages:
            writer.add_page(page)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()
