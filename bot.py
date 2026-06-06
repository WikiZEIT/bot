#!/usr/bin/env python

import re
import pywikibot

def main():
    site = pywikibot.Site('pl', 'wikipedia')
    cat = pywikibot.Category(site, 'Kategoria:Strony monitorowane przez bota WikiZEIT')

    for page in cat.articles():
        if not page.exists():
            continue

        pywikibot.output(f"Przetwarzam stronę: {page.title()}")
        text = page.text

        # 1. PRZYPADEK 1: Szukamy szablonu, który ma już przypisany licznik, np. {{WikiZEITBot|5}}
        # Grupa 1: całe dopasowanie, Grupa 2: aktualna liczba
        pattern_with_number = r"(\{\{(?:Wikipedysta|User):WikiZEITBot/szablon\|(\d+)\}\})"
        match = re.search(pattern_with_number, text, flags=re.I)

        if match:
            stary_szablon = match.group(1)
            aktualny_licznik = int(match.group(2))
            nowy_licznik = aktualny_licznik + 1
            nowy_szablon = f"{{{{user:WikiZEITBot/szablon|{nowy_licznik}}}}}"

            new_text = text.replace(stary_szablon, nowy_szablon)

        else:
            # 2. PRZYPADEK 2: Szablon jest "pusty", czyli {{Wikipedysta:WikiZEITBot/szablon}} lub {{Wikipedysta:WikiZEITBot/szablon|}}
            # Używamy regexa, który dopasuje opcjonalny pionowy pasek ze spacjami
            pattern_empty = r"\{\{(?:Wikipedysta|User):WikiZEITBot/szablon\s*\|?\s*\}\}"

            if re.search(pattern_empty, text, flags=re.I):
                # Zastępujemy pierwsze wystąpienie pustego szablonu wartością początkową "1"
                new_text = re.sub(pattern_empty, "{{user:WikiZEITBot/szablon|1}}", text, count=1, flags=re.I)
                nowy_licznik = 1
            else:
                pywikibot.output(f"Na stronie {page.title()} nie znaleziono szablonu WikiZEITBot.")
                continue

        # Zapobiegamy pustym edycjom (jeśli tekst się nie zmienił)
        if text != new_text:
            page.text = new_text
            page.save(
                summary=f"[WikiZEIT Test] Aktualizacja licznika do: {nowy_licznik}",
                minor=True
            )
            print(f"Sukces! Strona {page.title()} zaktualizowana do {nowy_licznik}")

if __name__ == '__main__':
    main()
