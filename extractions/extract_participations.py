#!/usr/bin/env python3
# Projet : Velo Liberte Palmares
# Version : 3.5
# Fonction : exporter les participations du club selon la saison cycliste.
#            Du 01/01 au 31/10 : année sélectionnée et année précédente.
#            À partir du 01/11 : année sélectionnée uniquement.

import csv
from datetime import date
import sys
from pathlib import Path
from subprocess import run

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://velo-liberte-palmares.be"
LOGIN_URL = BASE_URL + "/membres/login/?next=/participations/club/"
LOGIN_POST_URL = BASE_URL + "/membres/login/"
PARTICIPATIONS_URL = BASE_URL + "/participations/club/"
OUTPUT_DIR = Path("/home/sabine/Téléchargements")
SECRET_SERVICE = "velo-liberte-palmares-test"

EXPECTED_HEADERS = [
    "Date",
    "Randonnée",
    "Nom",
    "Parcours",
    "Challenges",
    "Homologuée",
]


def years_to_export(selected_year, run_date):
    """Retourner les années FFBC requises selon la date d’exécution.

    Du 1er janvier au 31 octobre, une saison nécessite l’année
    précédente et l’année courante. À partir du 1er novembre,
    l’année précédente n’est plus exportée.
    """
    if (run_date.month, run_date.day) < (11, 1):
        return [selected_year, selected_year - 1]
    return [selected_year]


def get_secret(field):
    """Récupérer une information d'identification dans le trousseau Linux."""
    result = run(
        [
            "secret-tool",
            "lookup",
            "service", SECRET_SERVICE,
            "field", field,
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(
            f"Impossible de récupérer le champ « {field} » "
            "dans le trousseau de clés."
        )

    return result.stdout.strip()


def read_participations(session, year):
    """Récupérer les participations du club pour une année précise."""
    response = session.get(
        PARTICIPATIONS_URL,
        params={"year": str(year)},
        timeout=30,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    if soup.find("input", attrs={"name": "password"}):
        raise RuntimeError(
            "La session n'est plus connectée au site FFBC."
        )

    table = soup.find("table", id="competitors-table")
    if table is None:
        raise RuntimeError(
            f"Tableau des participations introuvable pour {year}."
        )

    thead = table.find("thead")
    tbody = table.find("tbody")

    if thead is None or tbody is None:
        raise RuntimeError(
            f"Structure du tableau incomplète pour {year}."
        )

    headers = [
        cell.get_text(" ", strip=True)
        for cell in thead.find_all(["th", "td"])
    ]

    if headers != EXPECTED_HEADERS:
        raise RuntimeError(
            f"Colonnes inattendues pour {year} : {headers}"
        )

    rows = []

    for tr in tbody.find_all("tr"):
        cells = [
            cell.get_text(" ", strip=True)
            for cell in tr.find_all(["th", "td"])
        ]

        if not cells:
            continue

        # Ignorer les lignes qui ne contiennent qu'un message
        # d'absence de résultats, mais refuser une structure inattendue.
        if len(cells) != len(headers):
            if len(cells) == 1:
                continue
            raise RuntimeError(
                f"Ligne incorrecte pour {year} : "
                f"{len(cells)} cellules au lieu de {len(headers)}."
            )

        rows.append(cells)

    if not rows:
        raise RuntimeError(
            f"Aucune participation trouvée pour {year}. "
            "Aucun CSV ne sera créé pour cette année."
        )

    return headers, rows


def write_csv(year, headers, rows):
    """Écrire un CSV avec le séparateur ; et l'encodage UTF-8 BOM."""
    output_file = OUTPUT_DIR / f"RPA_participants_club_{year}.csv"
    temporary_file = OUTPUT_DIR / f"RPA_participants_club_{year}.csv.tmp"

    try:
        with temporary_file.open(
            "w", encoding="utf-8-sig", newline=""
        ) as csv_file:
            writer = csv.writer(csv_file, delimiter=";")
            writer.writerow(headers)
            writer.writerows(rows)

        temporary_file.replace(output_file)

    except Exception:
        if temporary_file.exists():
            temporary_file.unlink()
        raise

    print(f"Année {year} : {len(rows)} participations enregistrées.")
    print(f"Fichier : {output_file}")


def main():
    username = get_secret("username")
    password = get_secret("password")

    with requests.Session() as session:
        # Ouvrir le formulaire de connexion et récupérer le jeton CSRF.
        response = session.get(LOGIN_URL, timeout=30)
        response.raise_for_status()

        login_soup = BeautifulSoup(response.text, "html.parser")
        csrf_input = login_soup.find(
            "input", attrs={"name": "csrfmiddlewaretoken"}
        )

        if csrf_input is None or not csrf_input.get("value"):
            raise RuntimeError(
                "Jeton CSRF introuvable dans le formulaire de connexion."
            )

        csrf_token = csrf_input["value"]

        # Se connecter avec le compte du club.
        response = session.post(
            LOGIN_POST_URL,
            data={
                "csrfmiddlewaretoken": csrf_token,
                "username": username,
                "password": password,
            },
            headers={"Referer": LOGIN_URL},
            timeout=30,
        )
        response.raise_for_status()

        # Charger la page par défaut pour lire l'année sélectionnée.
        response = session.get(PARTICIPATIONS_URL, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        if soup.find("input", attrs={"name": "password"}):
            raise RuntimeError(
                "La connexion a échoué ou la session a expiré."
            )

        year_select = soup.find("select", id="id_year")
        if year_select is None:
            raise RuntimeError(
                "Impossible de trouver la liste déroulante des années."
            )

        selected_option = year_select.find("option", selected=True)

        if selected_option is None or not selected_option.get("value"):
            raise RuntimeError(
                "Impossible de déterminer l'année sélectionnée par défaut."
            )

        try:
            selected_year = int(selected_option["value"])
        except ValueError:
            raise RuntimeError("L'année sélectionnée est invalide.")

        run_date = date.today()
        years = years_to_export(selected_year, run_date)
        print(f"Date d’exécution : {run_date.isoformat()}")
        print("Années à exporter : " + " et ".join(map(str, years)))

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        # Chaque année est traitée séparément.
        for year in years:
            headers, rows = read_participations(session, year)
            write_csv(year, headers, rows)

    print("Export terminé.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERREUR : {exc}", file=sys.stderr)
        sys.exit(1)
