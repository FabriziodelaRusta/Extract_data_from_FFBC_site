#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
FFBC - Extraction du calendrier des randonnées

Version 3.0 - 24/10/2026

Fonctions :
- Extraction de tous les mois d'une année.
- Filtre les randonnées pour ne garder que celles du mois extrait.
- Export JSON/CSV mensuel.
- Fusion des exports mensuels en fichiers annuels.
"""

import argparse
import csv
import json
import re
import time
from datetime import date, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup


# ==================================================
# CONFIGURATION
# ==================================================

BASE_DIR = Path(__file__).resolve().parent

BASE_URL = "https://www.velo-liberte.be/wp-content/themes/zapedah-child"
URL_CALENDRIER = BASE_URL + "/assets/scripts/ajax_request_calendrier.php"
URL_DETAILS = BASE_URL + "/assets/scripts/ajax_request_popup_calendar.php"
URL_PAGE = "https://www.velo-liberte.be/calendrier/"

MOIS_FR = {
    "janvier": 1,
    "février": 2,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "août": 8,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "décembre": 12,
    "decembre": 12,
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
    ),
    "Referer": URL_PAGE,
}


# ==================================================
# OUTILS
# ==================================================

def parse_args():
    parser = argparse.ArgumentParser(description="Extraire le calendrier FFBC pour une année.")
    parser.add_argument(
        "--year",
        type=int,
        default=date.today().year,
        help="Année à extraire (par défaut: année en cours).",
    )
    return parser.parse_args()


def texte(element, separateur=" ", defaut=""):
    if element is None:
        return defaut
    return element.get_text(separator=separateur, strip=True)


def valeur_disponible(valeur):
    if valeur is None:
        return None

    valeur = str(valeur).strip()
    if valeur.upper() in ("", "N.A", "N/A", "NA", "-", "NONE"):
        return None
    return valeur


def extraire_date(texte_ligne):
    motif = (
        r"(?:Lundi|Mardi|Mercredi|Jeudi|Vendredi|Samedi|Dimanche)"
        r"\s+(\d{1,2})\s+([A-Za-zÀ-ÿ]+)\s+(\d{4})"
    )

    correspondance = re.search(motif, texte_ligne, flags=re.IGNORECASE)
    if not correspondance:
        return None

    jour = int(correspondance.group(1))
    nom_mois = correspondance.group(2).lower()
    annee = int(correspondance.group(3))
    mois = MOIS_FR.get(nom_mois)

    if mois is None:
        return None

    try:
        return date(annee, mois, jour).isoformat()
    except ValueError:
        return None


def extraire_lieu_liste(texte_ligne):
    resultat = {
        "province": None,
        "code_postal": None,
        "localite": None,
    }

    if not extraire_date(texte_ligne):
        return resultat

    motif_date = (
        r"(?:Lundi|Mardi|Mercredi|Jeudi|Vendredi|Samedi|Dimanche)"
        r"\s+\d{1,2}\s+[A-Za-zÀ-ÿ]+\s+\d{4}"
    )
    correspondance_date = re.search(motif_date, texte_ligne, flags=re.IGNORECASE)
    if not correspondance_date:
        return resultat

    apres_date = texte_ligne[correspondance_date.end():].strip()
    correspondance_lieu = re.search(
        r"(.+?)\s*-\s*(\d{4})\s+(.+)$",
        apres_date,
    )

    if correspondance_lieu:
        resultat["province"] = correspondance_lieu.group(1).strip()
        resultat["code_postal"] = correspondance_lieu.group(2)
        resultat["localite"] = correspondance_lieu.group(3).strip()

    return resultat


def extraire_distance(texte_distance):
    correspondance = re.search(
        r"(\d+(?:[.,]\d+)?)\s*km",
        texte_distance,
        flags=re.IGNORECASE,
    )
    if not correspondance:
        return None

    nombre = float(correspondance.group(1).replace(",", "."))
    if nombre.is_integer():
        return int(nombre)
    return nombre


def extraire_champ(soup, selecteur, prefixe=None):
    element = soup.select_one(selecteur)
    if element is None:
        return None

    resultat = texte(element)

    if prefixe:
        resultat = re.sub(
            "^" + re.escape(prefixe),
            "",
            resultat,
            flags=re.IGNORECASE,
        ).strip()

    return valeur_disponible(resultat)


def month_bounds(mois):
    first_day = date(mois.year, mois.month, 1)
    if mois.month == 12:
        last_day = date(mois.year, 12, 31)
    else:
        next_month = date(mois.year, mois.month + 1, 1)
        last_day = next_month - timedelta(days=1)
    return first_day, last_day


def filtrer_par_mois(randos, mois):
    first_day, last_day = month_bounds(mois)
    sorties = []

    for rando in randos:
        date_rando = rando.get("date")
        if not date_rando:
            continue

        try:
            dt = date.fromisoformat(date_rando)
        except ValueError:
            continue

        if first_day <= dt <= last_day:
            sorties.append(rando)

    return sorties


# ==================================================
# EXTRACTION DE LA LISTE DU CALENDRIER
# ==================================================

def recuperer_liste(session, mois):
    donnees = {
        "ajax": "1",
        "baseUrl": BASE_URL,
        "year_selected": str(mois.year),
        "challenge": "",
        "vtt_route": "",
        "province": "",
        "date": mois.isoformat(),
    }

    print(f"Récupération du calendrier : {mois.strftime('%m/%Y')}")

    reponse = session.post(
        URL_CALENDRIER,
        data=donnees,
        timeout=30,
    )
    reponse.raise_for_status()

    soup = BeautifulSoup(reponse.text, "html.parser")
    lignes = soup.select(".calendar-row-informations")

    randos = []
    identifiants_vus = set()

    for ligne in lignes:
        identifiant = (ligne.get("id") or "").strip()
        if not identifiant or identifiant in identifiants_vus:
            continue

        identifiants_vus.add(identifiant)

        nom = texte(ligne.select_one("b"))
        texte_ligne = texte(ligne)
        lieu = extraire_lieu_liste(texte_ligne)

        randos.append({
            "id": identifiant,
            "nom": nom or None,
            "date": extraire_date(texte_ligne),
            "province": lieu["province"],
            "code_postal": lieu["code_postal"],
            "localite": lieu["localite"],
            "texte_calendrier": texte_ligne,
        })

    return randos


# ==================================================
# EXTRACTION DES DETAILS D'UNE RANDONNEE
# ==================================================

def recuperer_details(session, rando):
    donnees = {
        "ajax": "1",
        "baseUrl": BASE_URL,
        "id": rando["id"],
    }

    reponse = session.post(
        URL_DETAILS,
        data=donnees,
        timeout=30,
    )
    reponse.raise_for_status()

    soup = BeautifulSoup(reponse.text, "html.parser")

    element_lieu = soup.select_one(".calendar-details-place")
    nom_lieu = None
    adresse = None
    lien_itineraire = None

    if element_lieu:
        lignes = [
            ligne.strip()
            for ligne in texte(element_lieu, "\n").splitlines()
            if ligne.strip()
        ]

        lignes = [
            ligne for ligne in lignes
            if ligne.lower() not in ("itinéraire", "itineraire")
            and not ligne.lower().startswith("lieu de départ")
        ]

        if lignes:
            nom_lieu = lignes[0]

        if len(lignes) > 1:
            adresse = lignes[1]

        lien = element_lieu.select_one('a[href*="google.com/maps"]')
        if lien:
            lien_itineraire = lien.get("href")

    rando["lieu_depart"] = valeur_disponible(nom_lieu)
    rando["adresse"] = valeur_disponible(adresse)
    rando["lien_itineraire"] = lien_itineraire

    if adresse:
        correspondance = re.search(r"(\d{4})\s+(.+)$", adresse)
        if correspondance:
            if not rando.get("code_postal"):
                rando["code_postal"] = correspondance.group(1)
            if not rando.get("localite"):
                rando["localite"] = correspondance.group(2).strip()

    rando["club"] = extraire_champ(
        soup,
        ".calendar-details-club",
        "Club organisateur :",
    )

    parcours = []
    for element in soup.select(".calendar-activities-row"):
        type_parcours = extraire_champ(
            element,
            ".calendar-activities-row-type",
            "Type :",
        )

        distance_texte = texte(
            element.select_one(".calendar-activities-row-km")
        )

        denivele_texte = texte(
            element.select_one(".calendar-activities-row-denivele")
        )

        difficulte = texte(
            element.select_one(".calendar-activities-row-dificulty")
        )

        horaires = texte(
            element.select_one(".calendar-activities-row-date")
        )

        ravito_texte = texte(
            element.select_one(".calendar-activities-row-ravito")
        )

        tarif = None
        correspondance_tarif = re.search(
            r"Tarif\s*:\s*(.+)",
            texte(element),
            flags=re.IGNORECASE,
        )
        if correspondance_tarif:
            tarif = valeur_disponible(correspondance_tarif.group(1))

        denivele = None
        correspondance_denivele = re.search(
            r"(?i)(?:Dénivelé|Denivele|Denivele\s*:\s*)\s*:\s*(.+)",
            denivele_texte,
        )
        if correspondance_denivele:
            denivele = valeur_disponible(correspondance_denivele.group(1))

        if denivele is None and denivele_texte:
            denivele = valeur_disponible(denivele_texte)

        parcours.append({
            "type": valeur_disponible(
                re.sub(
                    r"^Type\s*:\s*",
                    "",
                    type_parcours or "",
                    flags=re.IGNORECASE,
                )
            ),
            "distance_km": extraire_distance(distance_texte),
            "denivele": denivele,
            "difficulte": valeur_disponible(difficulte),
            "horaires": valeur_disponible(
                re.sub(r"^[^\d]*", "", horaires)
            ),
            "ravitaillement": valeur_disponible(
                re.sub(
                    r"^Ravito\s*:\s*",
                    "",
                    ravito_texte,
                    flags=re.IGNORECASE,
                )
            ),
            "tarif": tarif,
        })

    rando["parcours"] = parcours
    rando["remarque"] = extraire_champ(
        soup,
        ".calendar-details-note",
        "Remarque :",
    )

    liens = []
    for lien in soup.select(".calendar-details a[href]"):
        url = lien.get("href", "").strip()
        libelle = texte(lien)

        if url.startswith(("http://", "https://")) and url != lien_itineraire:
            liens.append({
                "libelle": libelle or None,
                "url": url,
            })

    rando["liens_externes"] = liens
    rando["latitude"] = None
    rando["longitude"] = None

    return rando


# ==================================================
# EXPORT
# ==================================================

def joindre(valeurs):
    return " ; ".join(
        str(valeur)
        for valeur in valeurs
        if valeur is not None and str(valeur).strip()
    )


def ligne_csv(rando):
    parcours = rando.get("parcours", [])

    return {
        "Identifiant": rando.get("id"),
        "Nom": rando.get("nom"),
        "Date": rando.get("date"),
        "Province": rando.get("province"),
        "Code postal": rando.get("code_postal"),
        "Localité": rando.get("localite"),
        "Lieu de départ": rando.get("lieu_depart"),
        "Adresse": rando.get("adresse"),
        "Club organisateur": rando.get("club"),
        "Types de parcours": joindre([p.get("type") for p in parcours]),
        "Distances (km)": joindre([
            f"{p['distance_km']} km" if p.get("distance_km") is not None else None
            for p in parcours
        ]),
        "Dénivelés": joindre([p.get("denivele") for p in parcours]),
        "Horaires": joindre([p.get("horaires") for p in parcours]),
        "Ravitaillements": joindre([p.get("ravitaillement") for p in parcours]),
        "Tarifs": joindre([p.get("tarif") for p in parcours]),
        "Nombre de parcours": len(parcours),
        "Remarque": rando.get("remarque"),
        "Lien itinéraire": rando.get("lien_itineraire"),
        "Latitude": rando.get("latitude"),
        "Longitude": rando.get("longitude"),
        "Texte calendrier": rando.get("texte_calendrier"),
    }


def exporter_mensuel(randos, mois):
    suffixe = mois.strftime("%Y-%m")
    fichier_json = BASE_DIR / f"calendrier_ffbc_{suffixe}.json"
    fichier_csv = BASE_DIR / f"calendrier_ffbc_{suffixe}.csv"

    document = {
        "source": URL_PAGE,
        "mois_extrait": suffixe,
        "date_extraction": date.today().isoformat(),
        "nombre_randonnées": len(randos),
        "randonnées": randos,
    }

    with fichier_json.open("w", encoding="utf-8") as fichier:
        json.dump(document, fichier, ensure_ascii=False, indent=2)

    colonnes = list(ligne_csv(randos[0]).keys()) if randos else [
        "Identifiant", "Nom", "Date", "Province",
        "Code postal", "Localité", "Lieu de départ",
        "Adresse", "Club organisateur", "Types de parcours",
        "Distances (km)", "Dénivelés", "Horaires",
        "Ravitaillements", "Tarifs", "Nombre de parcours",
        "Remarque", "Lien itinéraire", "Latitude", "Longitude",
        "Texte calendrier",
    ]

    with fichier_csv.open("w", encoding="utf-8-sig", newline="") as fichier:
        redacteur = csv.DictWriter(
            fichier,
            fieldnames=colonnes,
            delimiter=";",
            extrasaction="ignore",
        )
        redacteur.writeheader()
        for rando in randos:
            redacteur.writerow(ligne_csv(rando))

    print(f"Export mensuel : {fichier_json} / {fichier_csv}")


def fusionner_fichiers_mensuels(annee):
    fichiers_json = sorted(BASE_DIR.glob(f"calendrier_ffbc_{annee}-*.json"))
    toutes_randos = []
    ids_vus = set()

    for fichier in fichiers_json:
        with fichier.open("r", encoding="utf-8") as handle:
            contenu = json.load(handle)

        for rando in contenu.get("randonnées", []):
            identifiant = rando.get("id") or rando.get("nom") or rando.get("date")
            if not identifiant:
                continue
            if identifiant in ids_vus:
                continue
            ids_vus.add(identifiant)
            toutes_randos.append(rando)

    toutes_randos.sort(key=lambda r: (r.get("date") or "", r.get("nom") or ""))

    document = {
        "source": URL_PAGE,
        "annee": annee,
        "date_extraction": date.today().isoformat(),
        "nombre_randonnées": len(toutes_randos),
        "randonnées": toutes_randos,
    }

    fichier_final_json = BASE_DIR / f"calendrier_ffbc_{annee}.json"
    with fichier_final_json.open("w", encoding="utf-8") as fichier:
        json.dump(document, fichier, ensure_ascii=False, indent=2)

    print(f"Fichier annuel JSON : {fichier_final_json}")

    fichiers_csv = sorted(BASE_DIR.glob(f"calendrier_ffbc_{annee}-*.csv"))
    lignes = []
    fieldnames = None

    for fichier in fichiers_csv:
        with fichier.open("r", encoding="utf-8-sig", newline="") as handle:
            lecteur = csv.DictReader(handle, delimiter=";")
            if fieldnames is None:
                fieldnames = lecteur.fieldnames or []
            for ligne in lecteur:
                lignes.append(ligne)

    fichier_final_csv = BASE_DIR / f"calendrier_ffbc_{annee}.csv"
    if lignes and fieldnames:
        with fichier_final_csv.open("w", encoding="utf-8-sig", newline="") as handle:
            redacteur = csv.DictWriter(
                handle,
                fieldnames=fieldnames,
                delimiter=";",
            )
            redacteur.writeheader()
            redacteur.writerows(lignes)

        print(f"Fichier annuel CSV : {fichier_final_csv}")
    else:
        print(f"Aucune donnée CSV à fusionner pour l'année {annee}.")


def fusionner_toutes_les_annees():
    """Regroupe tous les exports mensuels disponibles dans un fichier global."""
    fichiers_json = sorted(
        fichier
        for fichier in BASE_DIR.glob("calendrier_ffbc_*-*.json")
        if re.fullmatch(r"calendrier_ffbc_\d{4}-\d{2}", fichier.stem)
    )
    toutes_randos = []
    cles_vues = set()
    annees = set()

    for fichier in fichiers_json:
        with fichier.open("r", encoding="utf-8") as handle:
            contenu = json.load(handle)

        annees.add(int(fichier.stem[-7:-3]))
        for rando in contenu.get("randonnées", []):
            identifiant = rando.get("id")
            cle = (identifiant, rando.get("date")) if identifiant else (
                rando.get("nom"), rando.get("date")
            )
            if not any(cle):
                continue
            if cle in cles_vues:
                continue
            cles_vues.add(cle)
            toutes_randos.append(rando)

    toutes_randos.sort(key=lambda r: (r.get("date") or "", r.get("nom") or ""))

    document = {
        "source": URL_PAGE,
        "annees": sorted(annees),
        "date_extraction": date.today().isoformat(),
        "nombre_randonnées": len(toutes_randos),
        "randonnées": toutes_randos,
    }

    fichier_final_json = BASE_DIR / "calendrier_ffbc.json"
    with fichier_final_json.open("w", encoding="utf-8") as fichier:
        json.dump(document, fichier, ensure_ascii=False, indent=2)

    colonnes = list(ligne_csv(toutes_randos[0]).keys()) if toutes_randos else [
        "Identifiant", "Nom", "Date", "Province",
        "Code postal", "Localité", "Lieu de départ",
        "Adresse", "Club organisateur", "Types de parcours",
        "Distances (km)", "Dénivelés", "Horaires",
        "Ravitaillements", "Tarifs", "Nombre de parcours",
        "Remarque", "Lien itinéraire", "Latitude", "Longitude",
        "Texte calendrier",
    ]
    fichier_final_csv = BASE_DIR / "calendrier_ffbc.csv"
    with fichier_final_csv.open("w", encoding="utf-8-sig", newline="") as fichier:
        redacteur = csv.DictWriter(
            fichier,
            fieldnames=colonnes,
            delimiter=";",
            extrasaction="ignore",
        )
        redacteur.writeheader()
        for rando in toutes_randos:
            redacteur.writerow(ligne_csv(rando))

    print(
        f"Fichiers toutes années : {fichier_final_json} / "
        f"{fichier_final_csv} ({len(toutes_randos)} randonnée(s), "
        f"années : {', '.join(map(str, sorted(annees))) or 'aucune'})"
    )


# ==================================================
# PROGRAMME PRINCIPAL
# ==================================================


def main():
    args = parse_args()
    annee = args.year

    # Commencer au mois actuel si année en cours,
    # sinon commencer en janvier de l'année demandée.
    aujourd_hui = date.today()

    if annee == aujourd_hui.year:
        mois_num = aujourd_hui.month
    else:
        mois_num = 1

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        while True:
            mois = date(annee, mois_num, 1)

            randos = recuperer_liste(session, mois)

            # Filtrer les randonnées du mois demandé
            randos_du_mois = filtrer_par_mois(randos, mois)

            print(
                f"Randonnées du mois {mois.strftime('%m/%Y')} "
                f"conservées : {len(randos_du_mois)}"
            )

            # Arrêt au premier mois sans randonnée
            if not randos_du_mois:
                print(
                    f"Aucune randonnée pour {mois.strftime('%m/%Y')}. "
                    "Fin de l'extraction."
                )
                break

            total = len(randos_du_mois)
            erreurs = 0

            for numero, rando in enumerate(randos_du_mois, start=1):
                try:
                    recuperer_details(session, rando)
                except requests.RequestException as erreur:
                    erreurs += 1
                    rando["erreur_details"] = str(erreur)
                    rando.setdefault("parcours", [])
                    rando.setdefault("liens_externes", [])

                    print(
                        f"Attention : détails indisponibles "
                        f"pour {rando['id']} - {rando.get('nom')}: "
                        f"{erreur}"
                    )

                if numero % 10 == 0 or numero == total:
                    print(
                        f"Progression {mois.strftime('%m/%Y')} : "
                        f"{numero}/{total}"
                    )

                time.sleep(0.1)

            exporter_mensuel(randos_du_mois, mois)

            if erreurs:
                print(
                    f"Attention : {erreurs} randonnée(s) "
                    f"n'ont pas pu être détaillées pour "
                    f"{mois.strftime('%m/%Y')}."
                )

            # Passer au mois suivant
            mois_num += 1

            if mois_num > 12:
                mois_num = 1
                annee += 1

        # Fusionner les fichiers annuels générés
        # pour toutes les années concernées.
        annees = {
            int(f.stem.split("_")[-1])
            for f in BASE_DIR.glob("calendrier_ffbc_*.json")
            if re.fullmatch(r"\d{4}", f.stem.split("_")[-1])
        }

        for annee_fusion in sorted(annees):
            fusionner_fichiers_mensuels(annee_fusion)

        # Créer aussi un fichier unique rassemblant les mois de toutes les années.
        fusionner_toutes_les_annees()

    except requests.RequestException as erreur:
        print(f"Erreur de connexion au calendrier FFBC : {erreur}")

    finally:
        session.close()


if __name__ == "__main__":
    main()