"""Registre coopératif des marques (voir Brand dans models.py) — rattache un
logo choisi une fois par un superadmin à toutes les promotions correspondantes,
par nom de marque, tous points de vente confondus."""

from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import Brand, Promotion


def _normalize(name: str) -> str:
    return name.strip().lower()


def find_brand(db: Session, brand_name: str) -> Brand | None:
    normalized = _normalize(brand_name or "")
    if not normalized:
        return None
    return db.query(Brand).filter(func.lower(Brand.name) == normalized).first()


def apply_brand_logo(db: Session, promo: Promotion) -> None:
    """Si une marque du registre correspond au nom de cette promotion et
    qu'aucun visuel n'a déjà été choisi à la main pour elle, lui attache le
    logo de la marque. Appelé à la création d'une promotion (saisie manuelle
    ou relevé Gmail) et à chaque modification du nom de marque."""
    if promo.logo_path:
        return
    brand = find_brand(db, promo.brand_name)
    if brand and brand.logo_path:
        promo.logo_path = brand.logo_path


def apply_brand_logo_to_all_matching(db: Session, brand: Brand) -> int:
    """Pousse le logo d'une marque sur ses promotions existantes qui n'ont pas
    déjà leur propre visuel, tous points de vente confondus — utilisé quand un
    superadmin crée ou remplace le logo d'une marque, pour rattraper les
    promotions déjà en base sans écraser un visuel déjà choisi à la main."""
    if not brand.logo_path:
        return 0
    promos = (
        db.query(Promotion)
        .filter(func.lower(Promotion.brand_name) == _normalize(brand.name), Promotion.logo_path.is_(None))
        .all()
    )
    for promo in promos:
        promo.logo_path = brand.logo_path
    db.commit()
    return len(promos)
